import uuid
from datetime import datetime, timedelta, timezone as dt_timezone

from django.contrib.admin.models import LogEntry
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import BusinessAdmin, ProviderEvent, ProviderSubscription, Restaurant
from .subscription_services import (
    add_calendar_months,
    apply_manual_subscription,
    apply_provider_event,
    resolve_subscription_entitlement,
)


@override_settings(
    SECURE_SSL_REDIRECT=False,
    ALLOW_TEST_SUBSCRIPTION_ENTITLEMENTS=False,
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
)
class RestaurantSubscriptionAdminTests(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser("root", "root@example.com", "pass")
        self.staff = User.objects.create_user("staff", "staff@example.com", "pass", is_staff=True)
        self.owner_user = User.objects.create_user("owner", "owner@example.com", "pass")
        self.owner = BusinessAdmin.objects.create(
            auth_user=self.owner_user,
            phone="+4915700012345",
            name="Restaurant Owner",
            email="owner@example.com",
            payment_status="unpaid",
        )
        self.restaurant = Restaurant.objects.create(admin=self.owner, name="Test Restaurant")
        self.url = reverse(
            "admin:business_menu_restaurant_subscription", args=[self.restaurant.pk]
        )

    def post_action(self, action, *, action_id=None, reason="Support decision", custom_end=""):
        return self.client.post(
            self.url,
            {
                "action": action,
                "action_id": action_id or uuid.uuid4(),
                "reason": reason,
                "custom_end": custom_end,
            },
        )

    def create_provider(self, *, end=None):
        return ProviderSubscription.objects.create(
            account=self.owner,
            provider=ProviderSubscription.Provider.GOOGLE,
            environment="production",
            external_id="safe-provider-reference",
            product_id="de.mybonusberlin.monthly:monthly",
            status=ProviderSubscription.Status.ACTIVE,
            current_period_end=end or timezone.now() + timedelta(days=60),
            will_renew=True,
            verification_source=ProviderSubscription.VerificationSource.PROVIDER,
        )

    def test_calendar_months_clamp_month_end_and_leap_year(self):
        jan_31 = datetime(2024, 1, 31, 12, tzinfo=dt_timezone.utc)
        leap_day = datetime(2024, 2, 29, 12, tzinfo=dt_timezone.utc)
        self.assertEqual(add_calendar_months(jan_31, 1), datetime(2024, 2, 29, 12, tzinfo=dt_timezone.utc))
        self.assertEqual(add_calendar_months(leap_day, 12), datetime(2025, 2, 28, 12, tzinfo=dt_timezone.utc))

    def test_grant_extend_expire_and_duplicate_post(self):
        self.client.force_login(self.superuser)
        action_id = uuid.uuid4()
        first = self.post_action("grant_month", action_id=action_id)
        duplicate = self.post_action("grant_month", action_id=action_id)
        self.assertEqual(first.status_code, 302)
        self.assertEqual(duplicate.status_code, 302)

        manual = ProviderSubscription.objects.get(provider="manual")
        self.assertEqual(manual.current_period_end, add_calendar_months(manual.last_event_at, 1))
        first_end = manual.current_period_end
        self.assertEqual(ProviderEvent.objects.filter(provider="manual").count(), 1)
        self.assertEqual(LogEntry.objects.filter(object_id=str(self.restaurant.pk)).count(), 1)

        extend_id = uuid.uuid4()
        self.assertNotEqual(action_id, extend_id)
        extended = self.post_action("extend_year", action_id=extend_id)
        self.assertEqual(extended.status_code, 302, extended.context and extended.context["form"].errors)
        self.assertEqual(extended.url, self.url)
        self.owner.refresh_from_db()
        self.assertEqual(self.owner.subscription_last_admin_action_id, extend_id)
        manual.refresh_from_db()
        self.assertEqual(
            manual.current_period_end,
            add_calendar_months(first_end, 12),
        )
        self.assertTrue(resolve_subscription_entitlement(self.owner, now=manual.current_period_end - timedelta(seconds=1))["is_entitled"])
        self.assertFalse(resolve_subscription_entitlement(self.owner, now=manual.current_period_end + timedelta(seconds=1))["is_entitled"])

    def test_cancel_manual_keeps_valid_provider(self):
        self.client.force_login(self.superuser)
        provider = self.create_provider()
        self.post_action("grant_year")
        self.assertEqual(resolve_subscription_entitlement(self.owner)["provider"], "manual")

        response = self.post_action("cancel_manual", reason="Manual grant withdrawn")
        self.assertEqual(response.status_code, 302)
        entitlement = resolve_subscription_entitlement(self.owner)
        self.assertTrue(entitlement["is_entitled"])
        self.assertEqual(entitlement["provider"], provider.provider)
        self.assertEqual(ProviderSubscription.objects.get(provider="manual").status, "revoked")

    def test_block_survives_provider_event_and_unblock_recalculates(self):
        self.client.force_login(self.superuser)
        provider = self.create_provider()
        self.post_action("block", reason="Abuse review")
        self.owner.refresh_from_db()
        blocked = resolve_subscription_entitlement(self.owner)
        self.assertFalse(blocked["is_entitled"])
        self.assertFalse(blocked["providers"][0]["is_entitled"])

        apply_provider_event(
            account=self.owner,
            provider=provider.provider,
            environment=provider.environment,
            external_id=provider.external_id,
            event_id="webhook-while-blocked",
            event_type="renewed",
            status=ProviderSubscription.Status.ACTIVE,
            current_period_end=timezone.now() + timedelta(days=90),
            occurred_at=timezone.now(),
            product_id=provider.product_id,
            will_renew=True,
            verification_source=ProviderSubscription.VerificationSource.PROVIDER,
        )
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.subscription_access_blocked)
        self.assertFalse(resolve_subscription_entitlement(self.owner)["is_entitled"])

        self.post_action("unblock", reason="Review completed")
        self.owner.refresh_from_db()
        entitlement = resolve_subscription_entitlement(self.owner)
        self.assertFalse(self.owner.subscription_access_blocked)
        self.assertTrue(entitlement["is_entitled"])
        self.assertEqual(entitlement["provider"], "google")
        self.assertTrue(entitlement["providers"][0]["is_entitled"])

    @override_settings(STRIPE_SECRET_KEY="sk_test", STRIPE_PUBLISHABLE_KEY="pk_test")
    def test_block_is_returned_by_subscription_api(self):
        apply_manual_subscription(
            self.owner,
            event_id="manual-before-block",
            plan="manual_pro",
            expires_at=timezone.now() + timedelta(days=3650),
        )
        self.owner.refresh_from_db()
        self.assertTrue(resolve_subscription_entitlement(self.owner)["is_entitled"])

        self.client.force_login(self.superuser)
        self.post_action("block", reason="Account review")

        self.client.logout()
        login = self.client.post(
            "/api/business-menu/login/",
            {"email": self.owner.email, "password": "pass"},
        )
        self.assertEqual(login.status_code, 200)
        self.assertEqual(login.json()["subscription"]["state"], "blocked")
        self.assertFalse(login.json()["subscription"]["is_entitled"])

        self.client.force_login(self.owner_user)
        response = self.client.get("/api/business-menu/admin/subscription/")
        restore = self.client.post("/api/business-menu/admin/subscription/restore/", {})
        gated = self.client.post(
            "/api/business-menu/api/create-connect-link/",
            {"admin_id": self.owner.pk},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["state"], "blocked")
        self.assertFalse(response.json()["is_entitled"])
        self.assertFalse(response.json()["providers"][0]["is_entitled"])
        self.assertEqual(restore.status_code, 200)
        self.assertEqual(restore.json()["subscription"]["state"], "blocked")
        self.assertFalse(restore.json()["subscription"]["is_entitled"])
        self.assertEqual(gated.status_code, 402)
        self.assertEqual(gated.json()["code"], "subscription_required")
        self.assertEqual(gated.json()["message"], "An active subscription is required.")

        other_user = User.objects.create_user("other-owner", "other@example.com", "pass")
        self.client.force_login(other_user)
        forbidden = self.client.post(
            "/api/business-menu/api/create-connect-link/",
            {"admin_id": self.owner.pk},
        )
        self.assertEqual(forbidden.status_code, 403)
        self.assertEqual(forbidden.json()["code"], "permission_denied")

    def test_custom_end_requires_a_future_date(self):
        self.client.force_login(self.superuser)
        today = timezone.localdate()

        invalid = self.post_action("grant_custom", custom_end=(today - timedelta(days=1)).isoformat())
        valid_end = today + timedelta(days=45)
        valid = self.post_action("grant_custom", custom_end=valid_end.isoformat())

        self.assertEqual(invalid.status_code, 200)
        self.assertContains(invalid, "must be in the future")
        self.assertEqual(valid.status_code, 302)
        manual = ProviderSubscription.objects.get(provider="manual")
        self.assertEqual(timezone.localtime(manual.current_period_end).date(), valid_end)

    def test_management_requires_superuser_and_renders_safe_details(self):
        self.create_provider()
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.post_action("block").status_code, 403)

        self.client.force_login(self.superuser)
        page = self.client.get(self.url)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Restaurant Owner")
        self.assertContains(page, "Test Restaurant")
        self.assertContains(page, "Google Play")
        self.assertNotContains(page, "safe-provider-reference")

        change_page = self.client.get(
            reverse("admin:business_menu_restaurant_change", args=[self.restaurant.pk])
        )
        list_page = self.client.get(reverse("admin:business_menu_restaurant_changelist"))
        self.assertContains(change_page, "Subscription")
        self.assertContains(change_page, "Manage subscription")
        self.assertContains(list_page, "Effective subscription")
        self.assertContains(list_page, "Manage subscription")
