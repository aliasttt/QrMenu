import base64
from io import StringIO
import json
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from .models import BusinessAdmin, ProviderEvent, ProviderSubscription
from .subscription_services import (
    GooglePlaySubscriptionResult,
    SubscriptionOwnershipError,
    SubscriptionRejectedError,
    SubscriptionTemporaryError,
    apply_google_play_subscription,
    decrypt_google_purchase_token,
    resolve_subscription_entitlement,
    verify_google_play_subscription,
    verify_google_pubsub_token,
)


GOOGLE_SETTINGS = {
    "GOOGLE_PLAY_PACKAGE_NAME": "de.example.qrmenu",
    "GOOGLE_PLAY_SUBSCRIPTION_PRODUCTS_JSON": json.dumps({"premium": ["monthly", "yearly"]}),
    "GOOGLE_PLAY_TOKEN_ENCRYPTION_KEY": "aKtPqco7XHo-fOtNO99evNt2M2dMZX0EwfGtMY9dQY4=",
    "GOOGLE_PUBSUB_AUDIENCE": "https://example.test/google-rtdn",
    "GOOGLE_PUBSUB_SERVICE_ACCOUNT_EMAIL": "push@example-project.iam.gserviceaccount.com",
    "ALLOW_TEST_SUBSCRIPTION_ENTITLEMENTS": False,
}


def make_admin(index=1):
    user = User.objects.create_user(username=f"google-admin-{index}")
    return BusinessAdmin.objects.create(
        auth_user=user,
        phone=f"+491570000{index:04d}",
        name=f"Google Admin {index}",
        email=f"google{index}@example.com",
        payment_status="unpaid",
    )


def google_payload(admin, **overrides):
    payload = {
        "subscriptionState": "SUBSCRIPTION_STATE_ACTIVE",
        "lineItems": [
            {
                "productId": "premium",
                "expiryTime": (timezone.now() + timedelta(days=30)).isoformat().replace("+00:00", "Z"),
                "latestSuccessfulOrderId": "GPA.1234-5678",
                "autoRenewingPlan": {"autoRenewEnabled": True},
                "offerDetails": {"basePlanId": "monthly"},
            }
        ],
        "externalAccountIdentifiers": {"obfuscatedExternalAccountId": str(admin.subscription_account_token)},
        "acknowledgementState": "ACKNOWLEDGEMENT_STATE_ACKNOWLEDGED",
        "etag": "etag-1",
    }
    payload.update(overrides)
    return payload


def result_from_payload(payload, token="purchase-token-1"):
    item = payload["lineItems"][0]
    state_map = {
        "SUBSCRIPTION_STATE_ACTIVE": "active",
        "SUBSCRIPTION_STATE_IN_GRACE_PERIOD": "grace_period",
        "SUBSCRIPTION_STATE_CANCELED": "canceled",
        "SUBSCRIPTION_STATE_EXPIRED": "expired",
        "SUBSCRIPTION_STATE_PAUSED": "unpaid",
        "SUBSCRIPTION_STATE_ON_HOLD": "unpaid",
        "SUBSCRIPTION_STATE_PENDING": "unknown",
    }
    return GooglePlaySubscriptionResult(
        payload=payload,
        purchase_token=token,
        environment="test" if "testPurchase" in payload else "production",
        product_id=item["productId"],
        base_plan_id=item["offerDetails"]["basePlanId"],
        status=state_map.get(payload["subscriptionState"], "unknown"),
        expires_at=timezone.datetime.fromisoformat(item["expiryTime"].replace("Z", "+00:00")),
        will_renew=item.get("autoRenewingPlan", {}).get("autoRenewEnabled"),
        latest_order_id=item.get("latestSuccessfulOrderId", ""),
        linked_purchase_token=payload.get("linkedPurchaseToken", ""),
        acknowledgement_pending=payload.get("acknowledgementState") == "ACKNOWLEDGEMENT_STATE_PENDING",
    )


@override_settings(**GOOGLE_SETTINGS)
class GooglePlayServiceTests(TestCase):
    def setUp(self):
        self.admin = make_admin()

    def test_verifier_uses_server_configuration_and_maps_provider_state(self):
        payload = google_payload(
            self.admin,
            subscriptionState="SUBSCRIPTION_STATE_CANCELED",
            testPurchase={},
        )
        response = SimpleNamespace(status_code=200, json=lambda: payload)
        with patch("business_menu.subscription_services._google_api_response", return_value=response) as api:
            result = verify_google_play_subscription("secret-token")

        self.assertEqual(result.status, "canceled")
        self.assertEqual(result.environment, "test")
        self.assertFalse(result.will_renew)
        self.assertIn("de.example.qrmenu", api.call_args.args[1])
        self.assertNotIn("secret-token", str(result.payload))

    def test_disallowed_product_or_base_plan_is_rejected(self):
        payload = google_payload(self.admin)
        payload["lineItems"][0]["offerDetails"]["basePlanId"] = "unlisted"
        response = SimpleNamespace(status_code=200, json=lambda: payload)
        with patch("business_menu.subscription_services._google_api_response", return_value=response):
            with self.assertRaises(SubscriptionRejectedError):
                verify_google_play_subscription("secret-token")

    def test_provider_lifecycle_states_are_mapped_without_client_claims(self):
        expected = {
            "SUBSCRIPTION_STATE_PENDING": "unknown",
            "SUBSCRIPTION_STATE_ACTIVE": "active",
            "SUBSCRIPTION_STATE_IN_GRACE_PERIOD": "grace_period",
            "SUBSCRIPTION_STATE_ON_HOLD": "unpaid",
            "SUBSCRIPTION_STATE_PAUSED": "unpaid",
            "SUBSCRIPTION_STATE_CANCELED": "canceled",
            "SUBSCRIPTION_STATE_EXPIRED": "expired",
            "SUBSCRIPTION_STATE_PENDING_PURCHASE_CANCELED": "expired",
        }
        for provider_state, internal_state in expected.items():
            with self.subTest(provider_state=provider_state):
                payload = google_payload(self.admin, subscriptionState=provider_state)
                if internal_state == "expired":
                    payload["lineItems"][0]["expiryTime"] = (timezone.now() - timedelta(days=1)).isoformat()
                response = SimpleNamespace(status_code=200, json=lambda payload=payload: payload)
                with patch("business_menu.subscription_services._google_api_response", return_value=response):
                    self.assertEqual(verify_google_play_subscription("secret-token").status, internal_state)

    def test_purchase_is_bound_once_and_raw_token_is_not_stored(self):
        result = result_from_payload(google_payload(self.admin))
        subscription, _, _ = apply_google_play_subscription(self.admin, result)

        other = make_admin(2)
        mismatch = result_from_payload(google_payload(other))
        with self.assertRaises(SubscriptionOwnershipError):
            apply_google_play_subscription(other, mismatch)

        subscription.refresh_from_db()
        self.assertNotIn(result.purchase_token, subscription.external_id)
        self.assertNotIn(result.purchase_token, subscription.provider_customer_id)
        self.assertEqual(decrypt_google_purchase_token(subscription.provider_customer_id), result.purchase_token)

    def test_missing_account_identifier_requires_existing_or_linked_binding(self):
        payload = google_payload(self.admin, externalAccountIdentifiers={})
        with self.assertRaises(SubscriptionOwnershipError):
            apply_google_play_subscription(self.admin, result_from_payload(payload))

        first = result_from_payload(google_payload(self.admin), token="old-token")
        apply_google_play_subscription(self.admin, first)
        linked_payload = google_payload(
            self.admin,
            externalAccountIdentifiers={},
            linkedPurchaseToken="old-token",
        )
        linked_payload["lineItems"][0]["latestSuccessfulOrderId"] = "GPA.9876-5432"
        apply_google_play_subscription(self.admin, result_from_payload(linked_payload, token="new-token"))
        self.assertEqual(ProviderSubscription.objects.filter(provider="google").count(), 2)

    def test_pending_is_not_acknowledged_or_entitled(self):
        payload = google_payload(
            self.admin,
            subscriptionState="SUBSCRIPTION_STATE_PENDING",
            acknowledgementState="ACKNOWLEDGEMENT_STATE_PENDING",
        )
        result = result_from_payload(payload)
        with patch("business_menu.subscription_services.acknowledge_google_play_subscription") as acknowledge:
            apply_google_play_subscription(self.admin, result)
        acknowledge.assert_not_called()
        self.assertFalse(resolve_subscription_entitlement(self.admin)["is_entitled"])

    def test_acknowledgement_failure_is_persisted_and_retryable(self):
        payload = google_payload(self.admin, acknowledgementState="ACKNOWLEDGEMENT_STATE_PENDING")
        result = result_from_payload(payload)
        with patch(
            "business_menu.subscription_services.acknowledge_google_play_subscription",
            side_effect=SubscriptionTemporaryError("temporary"),
        ):
            with self.assertRaises(SubscriptionTemporaryError):
                apply_google_play_subscription(self.admin, result)
        row = ProviderSubscription.objects.get(provider="google")
        self.assertTrue(row.needs_reconciliation)

        with patch("business_menu.subscription_services.acknowledge_google_play_subscription", return_value=True):
            _row, applied, outcome = apply_google_play_subscription(self.admin, result)
        row.refresh_from_db()
        self.assertFalse(applied)
        self.assertEqual(outcome, "duplicate")
        self.assertFalse(row.needs_reconciliation)

    def test_test_purchase_does_not_replace_independent_legacy_entitlement(self):
        self.admin.payment_status = "paid"
        self.admin.subscription_provider = "stripe"
        self.admin.subscription_environment = "live"
        self.admin.subscription_ends_at = timezone.now() + timedelta(days=10)
        self.admin.save()
        payload = google_payload(self.admin, testPurchase={}, subscriptionState="SUBSCRIPTION_STATE_PENDING")
        apply_google_play_subscription(self.admin, result_from_payload(payload))

        entitlement = resolve_subscription_entitlement(self.admin)
        self.assertTrue(entitlement["is_entitled"])
        self.assertEqual(entitlement["entitlement_source"], "legacy")
        self.assertEqual(entitlement["provider"], "stripe")

    def test_pubsub_identity_checks_audience_issuer_and_service_account(self):
        claims = {
            "iss": "https://accounts.google.com",
            "email": GOOGLE_SETTINGS["GOOGLE_PUBSUB_SERVICE_ACCOUNT_EMAIL"],
            "email_verified": True,
        }
        with patch("google.oauth2.id_token.verify_oauth2_token", return_value=claims) as verify:
            self.assertEqual(verify_google_pubsub_token("Bearer signed-token"), claims)
        self.assertEqual(verify.call_args.kwargs["audience"], GOOGLE_SETTINGS["GOOGLE_PUBSUB_AUDIENCE"])

        with patch("google.oauth2.id_token.verify_oauth2_token", return_value={**claims, "email": "other@example.com"}):
            with self.assertRaises(SubscriptionRejectedError):
                verify_google_pubsub_token("Bearer signed-token")

    def test_acknowledgement_retry_keeps_failure_queued_and_exits_nonzero(self):
        result = result_from_payload(
            google_payload(self.admin, acknowledgementState="ACKNOWLEDGEMENT_STATE_PENDING")
        )
        with patch(
            "business_menu.subscription_services.acknowledge_google_play_subscription",
            side_effect=SubscriptionTemporaryError("temporary"),
        ):
            with self.assertRaises(SubscriptionTemporaryError):
                apply_google_play_subscription(self.admin, result)

        with patch(
            "business_menu.management.commands.retry_google_play_acknowledgements.verify_google_play_subscription",
            side_effect=SubscriptionTemporaryError("temporary"),
        ):
            with self.assertRaises(CommandError):
                call_command("retry_google_play_acknowledgements", "--apply", stdout=StringIO())

        self.assertTrue(ProviderSubscription.objects.get(provider="google").needs_reconciliation)


@override_settings(SECURE_SSL_REDIRECT=False, **GOOGLE_SETTINGS)
class GooglePlayEndpointTests(APITestCase):
    def setUp(self):
        self.admin = make_admin()
        self.client.force_authenticate(self.admin.auth_user)

    def test_authenticated_verify_ignores_client_product_claims(self):
        result = result_from_payload(google_payload(self.admin))
        with patch("business_menu.views.verify_google_play_subscription", return_value=result):
            response = self.client.post(
                "/api/business-menu/admin/subscription/google/verify/",
                {"purchaseToken": result.purchase_token, "productId": "client-lie"},
                format="json",
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["product_id"], "premium")

    def _rtdn(self, message_id, result, event_time):
        notification = {
            "version": "1.0",
            "packageName": GOOGLE_SETTINGS["GOOGLE_PLAY_PACKAGE_NAME"],
            "eventTimeMillis": str(int(event_time.timestamp() * 1000)),
            "subscriptionNotification": {
                "version": "1.0",
                "notificationType": 2,
                "purchaseToken": result.purchase_token,
            },
        }
        envelope = {
            "message": {
                "messageId": message_id,
                "data": base64.b64encode(json.dumps(notification).encode()).decode(),
            }
        }
        self.client.force_authenticate(user=None)
        with patch("business_menu.views.verify_google_pubsub_token", return_value={}), patch(
            "business_menu.views.verify_google_play_subscription", return_value=result
        ) as verify:
            response = self.client.post(
                "/api/business-menu/admin/subscriptions/google/notifications/",
                envelope,
                format="json",
                HTTP_AUTHORIZATION="Bearer signed-token",
            )
        return response, verify

    def test_rtdn_requeries_google_deduplicates_and_does_not_roll_back(self):
        now = timezone.now()
        active = result_from_payload(google_payload(self.admin))
        apply_google_play_subscription(self.admin, active, event_id="initial", occurred_at=now)

        expired_payload = google_payload(self.admin, subscriptionState="SUBSCRIPTION_STATE_EXPIRED")
        expired_payload["lineItems"][0]["expiryTime"] = (now - timedelta(days=1)).isoformat()
        expired = result_from_payload(expired_payload)
        first, verify = self._rtdn("message-old", expired, now - timedelta(hours=1))
        replay, replay_verify = self._rtdn("message-old", expired, now - timedelta(hours=1))

        self.assertEqual(first.status_code, 200)
        self.assertFalse(first.data["state_applied"])
        self.assertEqual(replay.data["outcome"], "duplicate")
        verify.assert_called_once()
        replay_verify.assert_not_called()
        self.assertEqual(ProviderSubscription.objects.get(provider="google").status, "active")

    def test_unknown_rtdn_purchase_is_not_claimed(self):
        unknown = result_from_payload(google_payload(self.admin), token="unknown-token")
        response, verify = self._rtdn("message-unknown", unknown, timezone.now())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["detail"], "unknown_purchase")
        verify.assert_not_called()
        self.assertFalse(ProviderSubscription.objects.exists())
