from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core import signing
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from .models import BusinessAdmin, Restaurant
from .subscription_services import apply_manual_subscription


@override_settings(
    SECURE_SSL_REDIRECT=False,
    STRIPE_SECRET_KEY="sk_test_fake",
    STRIPE_PUBLISHABLE_KEY="pk_test_fake",
    SITE_URL="https://preismenu.de",
    ALLOW_TEST_SUBSCRIPTION_ENTITLEMENTS=False,
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
)
class StripeConnectFlowTests(TestCase):
    def setUp(self):
        BusinessAdmin.objects.create(phone="+490000000001", name="Unlinked")
        self.user = User.objects.create_user("restaurant-owner", password="pass")
        self.other_user = User.objects.create_user("other-owner", password="pass")
        self.admin = BusinessAdmin.objects.create(
            auth_user=self.user,
            phone="+490000000002",
            name="Owner",
            email="owner@example.com",
            payment_status="unpaid",
            stripe_account_id="acct_existing",
        )
        self.restaurant = Restaurant.objects.create(admin=self.admin, name="Restaurant")
        apply_manual_subscription(
            self.admin,
            event_id="connect-flow-active",
            plan="manual_pro",
            expires_at=timezone.now() + timedelta(days=30),
        )
        self.client = APIClient()

    def signed_continuation(self):
        return signing.dumps(
            {"admin_id": self.admin.pk, "account_id": self.admin.stripe_account_id},
            salt="stripe-connect-continuation",
        )

    @patch("stripe.AccountLink.create", return_value=SimpleNamespace(url="https://connect.stripe.test/onboarding"))
    @patch("stripe.Account.create")
    @patch("stripe.Account.modify")
    def test_legacy_route_maps_restaurant_id_and_reuses_existing_account(self, modify_account, create_account, create_link):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(self.user)}")
        response = self.client.get(f"/api/business-menu/stripe-connect/{self.restaurant.pk}/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"success": True, "url": "https://connect.stripe.test/onboarding"})
        create_account.assert_not_called()
        modify_account.assert_called_once_with(
            "acct_existing", capabilities={"transfers": {"requested": True}},
        )
        kwargs = create_link.call_args.kwargs
        self.assertEqual(kwargs["account"], "acct_existing")
        self.assertIn("https://preismenu.de/business-menu/connect/refresh/?continuation=", kwargs["refresh_url"])
        self.assertIn("https://preismenu.de/business-menu/connect/done/?continuation=", kwargs["return_url"])
        self.assertNotIn("admin_id", kwargs["return_url"])

    def test_legacy_route_requires_authentication_and_owner(self):
        guest = self.client.get(f"/api/business-menu/stripe-connect/{self.restaurant.pk}/")
        self.assertIn(guest.status_code, (401, 403))
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(self.other_user)}")
        forbidden = self.client.get(f"/api/business-menu/stripe-connect/{self.restaurant.pk}/")
        self.assertEqual(forbidden.status_code, 403)
        self.assertEqual(forbidden.json()["code"], "permission_denied")

    @patch("stripe.AccountLink.create", return_value=SimpleNamespace(url="https://connect.stripe.test/onboarding"))
    @patch("stripe.Account.modify")
    @patch("stripe.Account.create", return_value=SimpleNamespace(id="acct_new"))
    def test_canonical_post_creates_one_account_and_reuses_it_on_retry(self, create_account, modify_account, create_link):
        self.admin.stripe_account_id = ""
        self.admin.save(update_fields=["stripe_account_id"])
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(self.user)}")
        url = "/api/business-menu/api/create-connect-link/"

        first = self.client.post(url, {"admin_id": self.admin.pk}, format="json")
        second = self.client.post(url, {"admin_id": self.admin.pk}, format="json")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        create_account.assert_called_once_with(
            type="express",
            email="owner@example.com",
            capabilities={"transfers": {"requested": True}},
            idempotency_key=f"qrmenu-connect-{self.admin.pk}",
        )
        modify_account.assert_called_once_with("acct_new", capabilities={"transfers": {"requested": True}})
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.stripe_account_id, "acct_new")

    def test_legacy_route_gives_404_for_unknown_restaurant_and_402_when_blocked(self):
        self.client.force_login(self.user)
        missing = self.client.get("/api/business-menu/stripe-connect/999999/")
        self.assertEqual(missing.status_code, 404)
        self.admin.subscription_access_blocked = True
        self.admin.save(update_fields=["subscription_access_blocked"])
        blocked = self.client.get(f"/api/business-menu/stripe-connect/{self.restaurant.pk}/")
        self.assertEqual(blocked.status_code, 402)
        self.assertEqual(blocked.json()["code"], "subscription_required")

    def test_browser_entry_requires_owner_session(self):
        guest = self.client.get("/business-menu/connect/")
        self.assertIn(guest.status_code, (401, 403))
        self.client.force_login(self.user)
        with (
            patch("stripe.AccountLink.create", return_value=SimpleNamespace(url="https://connect.stripe.test/onboarding")),
            patch("stripe.Account.modify"),
        ):
            response = self.client.get("/business-menu/connect/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "https://connect.stripe.test/onboarding")

    @patch("stripe.AccountLink.create", return_value=SimpleNamespace(url="https://connect.stripe.test/refreshed"))
    @patch("stripe.Account.create")
    @patch("stripe.Account.modify")
    def test_expired_link_refresh_reuses_account_without_public_id_lookup(self, modify_account, create_account, create_link):
        response = self.client.get(f"/business-menu/connect/refresh/?continuation={self.signed_continuation()}")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "https://connect.stripe.test/refreshed")
        create_account.assert_not_called()
        self.assertEqual(create_link.call_args.kwargs["account"], "acct_existing")

    def test_expired_continuation_is_rejected(self):
        with patch("django.core.signing.time.time", return_value=timezone.now().timestamp() - 7200):
            expired = self.signed_continuation()
        response = self.client.get(f"/business-menu/connect/refresh/?continuation={expired}")
        self.assertEqual(response.status_code, 400)

    def test_refresh_reports_inactive_subscription_as_payment_required(self):
        self.admin.subscription_access_blocked = True
        self.admin.save(update_fields=["subscription_access_blocked"])
        response = self.client.get(f"/business-menu/connect/refresh/?continuation={self.signed_continuation()}")
        self.assertEqual(response.status_code, 402)

    @patch("stripe.Account.retrieve", return_value={
        "charges_enabled": False,
        "capabilities": {"transfers": "pending"},
        "requirements": {"currently_due": ["individual.verification.document"]},
    })
    def test_return_checks_stripe_state_instead_of_declaring_success(self, retrieve):
        response = self.client.get(f"/business-menu/connect/done/?continuation={self.signed_continuation()}")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Stripe setup incomplete")
        self.assertNotContains(response, "Stripe confirms your account can receive customer payments.")
        retrieve.assert_called_once_with("acct_existing")

    @patch("stripe.Account.retrieve", return_value={
        "charges_enabled": True,
        "capabilities": {"transfers": "active"},
        "requirements": {"currently_due": [], "past_due": []},
    })
    def test_return_confirms_only_fully_ready_account(self, retrieve):
        response = self.client.get(f"/business-menu/connect/done/?continuation={self.signed_continuation()}")
        self.assertContains(response, "Stripe confirms your account can receive customer payments.")

    @override_settings(DEBUG=False)
    def test_production_404_does_not_disclose_urlconf(self):
        response = self.client.get("/route-that-does-not-exist-for-connect-test/")
        body = response.content.decode()
        self.assertEqual(response.status_code, 404)
        self.assertNotIn("URLconf", body)
        self.assertNotIn("urlpatterns", body)
