from datetime import timedelta
import threading
from types import SimpleNamespace
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.db import DatabaseError, close_old_connections, connection
from django.core import signing
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken
from unittest import skipUnless

from .models import BusinessAdmin, Restaurant
from .subscription_services import apply_manual_subscription
from .stripe_views import ConnectRequestInProgress, _create_connect_link


@contextmanager
def mocked_connect_stripe(account_id="acct_new", url="https://connect.stripe.test/onboarding"):
    client = SimpleNamespace(
        accounts=SimpleNamespace(create=MagicMock(return_value=SimpleNamespace(id=account_id))),
        account_links=SimpleNamespace(create=MagicMock(return_value=SimpleNamespace(url=url))),
    )
    with patch("stripe.StripeClient", return_value=client), patch("stripe.RequestsClient"):
        yield client


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
        BusinessAdmin.objects.create(phone="+493012345601", name="Unlinked", email="unlinked@example.test")
        self.user = User.objects.create_user("restaurant-owner", password="pass")
        self.other_user = User.objects.create_user("other-owner", password="pass")
        self.admin = BusinessAdmin.objects.create(
            auth_user=self.user,
            phone="+493012345602",
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

    def test_legacy_route_maps_restaurant_id_and_reuses_existing_account(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(self.user)}")
        with mocked_connect_stripe() as stripe_client:
            response = self.client.get(f"/api/business-menu/stripe-connect/{self.restaurant.pk}/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"success": True, "url": "https://connect.stripe.test/onboarding"})
        self.assertEqual(response["Cache-Control"], "no-store")
        stripe_client.accounts.create.assert_not_called()
        kwargs = stripe_client.account_links.create.call_args.kwargs["params"]
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

    def test_app_onboarding_link_route_uses_restaurant_id_and_reuses_account(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(self.user)}")
        path = f"/api/business-menu/stripe-connect/{self.restaurant.pk}/onboarding-link/"
        self.assertNotEqual(self.restaurant.pk, self.admin.pk)

        with mocked_connect_stripe() as stripe_client:
            response = self.client.post(path, {}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"success": True, "url": "https://connect.stripe.test/onboarding"})
        self.assertEqual(response["Cache-Control"], "no-store")
        stripe_client.accounts.create.assert_not_called()
        self.assertEqual(stripe_client.account_links.create.call_args.kwargs["params"]["account"], "acct_existing")

    def test_app_onboarding_link_retry_does_not_create_another_account(self):
        self.admin.stripe_account_id = ""
        self.admin.save(update_fields=["stripe_account_id"])
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(self.user)}")
        path = f"/api/business-menu/stripe-connect/{self.restaurant.pk}/onboarding-link/"

        with mocked_connect_stripe() as stripe_client:
            first = self.client.post(path, {}, format="json")
            retry = self.client.post(path, {}, format="json")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(retry.status_code, 200)
        stripe_client.accounts.create.assert_called_once()
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.stripe_account_id, "acct_new")

    def test_app_onboarding_link_timeout_returns_retryable_json(self):
        import stripe

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(self.user)}")
        path = f"/api/business-menu/stripe-connect/{self.restaurant.pk}/onboarding-link/"
        with mocked_connect_stripe() as stripe_client:
            stripe_client.account_links.create.side_effect = stripe.APIConnectionError("timeout")
            response = self.client.post(path, {}, format="json")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["code"], "stripe_connect_temporary")
        self.assertEqual(response["Cache-Control"], "no-store")

    def test_app_onboarding_link_route_rejects_guest_other_owner_and_unknown_restaurant(self):
        path = f"/api/business-menu/stripe-connect/{self.restaurant.pk}/onboarding-link/"
        guest = self.client.post(path, {}, format="json")
        self.assertIn(guest.status_code, (401, 403))

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(self.other_user)}")
        forbidden = self.client.post(path, {}, format="json")
        self.assertEqual(forbidden.status_code, 403)
        self.assertEqual(forbidden.json()["code"], "permission_denied")

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(self.user)}")
        missing = self.client.post("/api/business-menu/stripe-connect/999999/onboarding-link/", {}, format="json")
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.json()["code"], "not_found")

    def test_canonical_post_creates_one_account_and_reuses_it_on_retry(self):
        self.admin.stripe_account_id = ""
        self.admin.save(update_fields=["stripe_account_id"])
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(self.user)}")
        url = "/api/business-menu/api/create-connect-link/"

        with mocked_connect_stripe() as stripe_client:
            first = self.client.post(url, {"admin_id": self.admin.pk}, format="json")
            second = self.client.post(url, {"admin_id": self.admin.pk}, format="json")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first["Cache-Control"], "no-store")
        stripe_client.accounts.create.assert_called_once_with(
            params={
                "type": "express",
                "email": "owner@example.com",
                "capabilities": {"transfers": {"requested": True}},
            },
            options={"idempotency_key": f"qrmenu-connect-{self.admin.pk}"},
        )
        stripe_client.account_links.create.assert_called()
        client_options = stripe_client.account_links.create.call_args
        self.assertEqual(client_options.kwargs["params"]["account"], "acct_new")
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.stripe_account_id, "acct_new")

    def test_connect_uses_short_stripe_timeout_without_retries(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(self.user)}")
        client = SimpleNamespace(
            accounts=SimpleNamespace(create=MagicMock(return_value=SimpleNamespace(id="acct_new"))),
            account_links=SimpleNamespace(create=MagicMock(return_value=SimpleNamespace(url="https://connect.stripe.test/onboarding"))),
        )
        with patch("stripe.StripeClient", return_value=client) as stripe_client, patch("stripe.RequestsClient") as http_client:
            response = self.client.get(f"/api/business-menu/stripe-connect/{self.restaurant.pk}/")
        self.assertEqual(response.status_code, 200)
        http_client.assert_called_once_with(timeout=4)
        stripe_client.assert_called_once_with(
            "sk_test_fake", max_network_retries=0, http_client=http_client.return_value,
        )

    def test_simultaneous_request_gets_controlled_in_progress_response(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(self.user)}")
        lock_key = f"stripe-connect-onboarding:test:{self.admin.pk}"
        cache.set(lock_key, "another-request", timeout=30)
        with mocked_connect_stripe() as stripe_client:
            response = self.client.get(f"/api/business-menu/stripe-connect/{self.restaurant.pk}/")
        cache.delete(lock_key)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "stripe_connect_in_progress")
        self.assertEqual(response["Cache-Control"], "no-store")
        stripe_client.account_links.create.assert_not_called()

    def test_timeout_returns_retryable_json(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(self.user)}")
        with mocked_connect_stripe() as stripe_client:
            import stripe
            stripe_client.account_links.create.side_effect = stripe.APIConnectionError("timeout")
            response = self.client.get(f"/api/business-menu/stripe-connect/{self.restaurant.pk}/")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["code"], "stripe_connect_temporary")
        self.assertIn("retry", response.json()["message"].lower())

    def test_retry_after_database_save_failure_reuses_stripe_idempotency_key(self):
        self.admin.stripe_account_id = ""
        self.admin.save(update_fields=["stripe_account_id"])
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(self.user)}")
        original_save = BusinessAdmin.save
        fail_once = {"pending": True}

        def save_with_one_failure(instance, *args, **kwargs):
            if (instance.pk == self.admin.pk and kwargs.get("update_fields") == ["stripe_account_id"]
                    and fail_once["pending"]):
                fail_once["pending"] = False
                raise DatabaseError("simulated persistence failure")
            return original_save(instance, *args, **kwargs)

        with mocked_connect_stripe() as stripe_client, patch.object(BusinessAdmin, "save", new=save_with_one_failure):
            first = self.client.get(f"/api/business-menu/stripe-connect/{self.restaurant.pk}/")
            second = self.client.get(f"/api/business-menu/stripe-connect/{self.restaurant.pk}/")

        self.assertEqual(first.status_code, 503)
        self.assertEqual(first.json()["code"], "stripe_connect_persistence_failed")
        self.assertEqual(second.status_code, 200)
        self.assertEqual(stripe_client.accounts.create.call_count, 2)
        self.assertEqual(
            [call.kwargs["options"]["idempotency_key"] for call in stripe_client.accounts.create.call_args_list],
            [f"qrmenu-connect-{self.admin.pk}"] * 2,
        )
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
        with mocked_connect_stripe():
            response = self.client.get("/business-menu/connect/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "https://connect.stripe.test/onboarding")

    def test_expired_link_refresh_reuses_account_without_public_id_lookup(self):
        with mocked_connect_stripe(url="https://connect.stripe.test/refreshed") as stripe_client:
            response = self.client.get(f"/business-menu/connect/refresh/?continuation={self.signed_continuation()}")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "https://connect.stripe.test/refreshed")
        stripe_client.accounts.create.assert_not_called()
        self.assertEqual(stripe_client.account_links.create.call_args.kwargs["params"]["account"], "acct_existing")

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


@override_settings(
    STRIPE_SECRET_KEY="sk_test_fake",
    STRIPE_PUBLISHABLE_KEY="pk_test_fake",
    SITE_URL="https://preismenu.de",
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "stripe-connect-concurrency"}},
)
class StripeConnectConcurrencyTests(TransactionTestCase):
    @skipUnless(connection.vendor == "postgresql", "concurrency behavior requires PostgreSQL")
    def test_concurrent_requests_share_one_create_and_persisted_account(self):
        user = User.objects.create_user("parallel-owner", password="pass")
        admin = BusinessAdmin.objects.create(
            auth_user=user, phone="+493012345699", name="Parallel", email="parallel@example.test",
        )
        cache.clear()
        entered = threading.Event()
        release = threading.Event()
        create_account = MagicMock(side_effect=lambda **kwargs: (
            entered.set(), release.wait(5), SimpleNamespace(id="acct_parallel"),
        )[2])
        client = SimpleNamespace(
            accounts=SimpleNamespace(create=create_account),
            account_links=SimpleNamespace(create=MagicMock(return_value=SimpleNamespace(url="https://connect.stripe.test/onboarding"))),
        )
        request = SimpleNamespace(build_absolute_uri=lambda path: f"https://preismenu.de{path}")
        outcomes = []

        def run(request_id):
            close_old_connections()
            try:
                outcomes.append(_create_connect_link(BusinessAdmin.objects.get(pk=admin.pk), request, request_id))
            except Exception as exc:
                outcomes.append(exc)
            finally:
                close_old_connections()

        with patch("stripe.StripeClient", return_value=client), patch("stripe.RequestsClient"):
            first = threading.Thread(target=run, args=("request-one",))
            first.start()
            self.assertTrue(entered.wait(5), "first request did not reach the mocked Stripe call")
            second = threading.Thread(target=run, args=("request-two",))
            second.start()
            second.join(5)
            release.set()
            first.join(5)

        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(create_account.call_count, 1)
        self.assertEqual(sum(isinstance(item, ConnectRequestInProgress) for item in outcomes), 1)
        self.assertEqual(sum(item == "https://connect.stripe.test/onboarding" for item in outcomes), 1)
        admin.refresh_from_db()
        self.assertEqual(admin.stripe_account_id, "acct_parallel")
