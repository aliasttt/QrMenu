from datetime import timedelta
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from .models import BusinessAdmin, ProviderEvent, ProviderSubscription
from .serializers import BusinessMenuSubscriptionSerializer
from .subscription_services import (
    AppleTransactionResult,
    SubscriptionConfigurationError,
    SubscriptionOwnershipError,
    SubscriptionRejectedError,
    _verify_apple_certificate_chain,
    apply_apple_transaction_to_admin,
    apply_provider_event,
    resolve_subscription_entitlement,
)


def make_admin(index=1, **overrides):
    values = {
        "phone": f"+4915900000{index:03d}",
        "name": f"Admin {index}",
        "email": f"owner{index}@example.com",
        "payment_status": "unpaid",
    }
    values.update(overrides)
    return BusinessAdmin.objects.create(**values)


@override_settings(
    ALLOW_TEST_SUBSCRIPTION_ENTITLEMENTS=False,
    LEGACY_SUBSCRIPTION_FALLBACK_ENABLED=True,
)
class EntitlementResolutionTests(TestCase):
    def setUp(self):
        self.admin = make_admin()
        self.now = timezone.now()

    def create_subscription(self, provider, environment, external_id, **overrides):
        values = {
            "account": self.admin,
            "provider": provider,
            "environment": environment,
            "external_id": external_id,
            "product_id": f"{provider}.annual",
            "status": ProviderSubscription.Status.ACTIVE,
            "current_period_end": self.now + timedelta(days=30),
            "will_renew": True,
            "verification_source": ProviderSubscription.VerificationSource.PROVIDER,
        }
        values.update(overrides)
        return ProviderSubscription.objects.create(**values)

    def test_two_valid_providers_and_one_expiry_do_not_destroy_entitlement(self):
        apple = self.create_subscription("apple", "production", "apple-original")
        stripe = self.create_subscription(
            "stripe",
            "live",
            "sub_live",
            current_period_end=self.now + timedelta(days=60),
        )

        result = resolve_subscription_entitlement(self.admin, now=self.now)
        self.assertTrue(result["is_entitled"])
        self.assertEqual(result["provider"], "stripe")
        self.assertEqual(sum(row["is_entitled"] for row in result["providers"]), 2)

        stripe.status = ProviderSubscription.Status.EXPIRED
        stripe.current_period_end = self.now - timedelta(seconds=1)
        stripe.save(update_fields=["status", "current_period_end"])
        result = resolve_subscription_entitlement(self.admin, now=self.now)
        self.assertTrue(result["is_entitled"])
        self.assertEqual(result["provider"], apple.provider)

    def test_canceled_renewal_keeps_access_until_period_end(self):
        self.create_subscription(
            "apple",
            "production",
            "apple-canceled",
            status=ProviderSubscription.Status.CANCELED,
            will_renew=False,
        )

        result = resolve_subscription_entitlement(self.admin, now=self.now)

        self.assertTrue(result["is_entitled"])
        self.assertFalse(result["will_renew"])

    def test_missing_renewal_information_stays_unknown(self):
        self.create_subscription("apple", "production", "apple-unknown-renewal", will_renew=None)
        self.assertIsNone(resolve_subscription_entitlement(self.admin, now=self.now)["will_renew"])

    def test_internal_trial_survives_provider_revocation(self):
        self.admin.payment_status = "paid"
        self.admin.trial_ends_at = self.now + timedelta(days=2)
        self.admin.save(update_fields=["payment_status", "trial_ends_at"])
        self.create_subscription(
            "apple",
            "production",
            "apple-revoked",
            status=ProviderSubscription.Status.REVOKED,
            current_period_end=self.now,
            will_renew=False,
        )

        result = resolve_subscription_entitlement(self.admin, now=self.now)

        self.assertTrue(result["is_entitled"])
        self.assertEqual(result["state"], "trial")
        self.assertEqual(result["trial_source"], "internal")

    def test_sandbox_does_not_entitle_normal_account(self):
        self.create_subscription("apple", "sandbox", "apple-sandbox")
        self.assertFalse(resolve_subscription_entitlement(self.admin, now=self.now)["is_entitled"])

    @override_settings(ALLOW_TEST_SUBSCRIPTION_ENTITLEMENTS=True)
    def test_sandbox_entitlement_requires_explicit_opt_in(self):
        self.create_subscription("apple", "sandbox", "apple-sandbox-opt-in")
        self.assertTrue(resolve_subscription_entitlement(self.admin, now=self.now)["is_entitled"])

    def test_legacy_response_keys_are_preserved_and_additions_are_safe(self):
        self.admin.payment_status = "paid"
        self.admin.subscription_ends_at = self.now + timedelta(days=5)
        self.admin.subscription_provider = "stripe"
        self.admin.subscription_product_id = "price_legacy"
        self.admin.save()

        payload = BusinessMenuSubscriptionSerializer(self.admin).data

        expected_legacy_keys = {
            "state",
            "is_entitled",
            "plan",
            "provider",
            "current_period_end",
            "will_renew",
            "trial_end",
            "purchasable_in_app",
            "manage_url",
            "message",
        }
        self.assertTrue(expected_legacy_keys.issubset(payload))
        self.assertTrue(payload["is_entitled"])
        self.assertEqual(payload["entitlement_source"], "legacy")
        self.assertIn("providers", payload)
        self.assertIn("app_account_token", payload)
        self.assertEqual(payload["app_account_token"], str(self.admin.subscription_account_token))
        self.admin.refresh_from_db()
        self.assertEqual(payload["app_account_token"], str(self.admin.subscription_account_token))


@override_settings(ALLOW_TEST_SUBSCRIPTION_ENTITLEMENTS=False)
class ProviderEventTests(TestCase):
    def setUp(self):
        self.admin = make_admin()
        self.other_admin = make_admin(2)
        self.now = timezone.now()

    def apply(self, **overrides):
        values = {
            "account": self.admin,
            "provider": "apple",
            "environment": "production",
            "external_id": "original-1",
            "event_id": "event-1",
            "event_type": "DID_RENEW",
            "status": ProviderSubscription.Status.ACTIVE,
            "current_period_end": self.now + timedelta(days=30),
            "occurred_at": self.now,
            "product_id": "de.preismenu.monthly",
            "latest_transaction_id": "transaction-1",
            "will_renew": True,
        }
        values.update(overrides)
        return apply_provider_event(**values)

    def test_duplicate_event_is_idempotent(self):
        subscription, applied, outcome = self.apply()
        duplicate, applied_again, duplicate_outcome = self.apply(
            current_period_end=self.now + timedelta(days=365)
        )

        subscription.refresh_from_db()
        self.assertEqual(subscription.pk, duplicate.pk)
        self.assertTrue(applied)
        self.assertEqual(outcome, "applied")
        self.assertFalse(applied_again)
        self.assertEqual(duplicate_outcome, "duplicate")
        self.assertEqual(subscription.current_period_end, self.now + timedelta(days=30))
        self.assertEqual(ProviderEvent.objects.count(), 1)

    def test_out_of_order_event_is_recorded_without_rolling_state_back(self):
        subscription, _, _ = self.apply()
        _subscription, applied, outcome = self.apply(
            event_id="event-old",
            latest_transaction_id="transaction-old",
            status=ProviderSubscription.Status.REVOKED,
            current_period_end=self.now - timedelta(days=1),
            occurred_at=self.now - timedelta(minutes=1),
        )

        subscription.refresh_from_db()
        self.assertFalse(applied)
        self.assertEqual(outcome, "stale")
        self.assertEqual(subscription.status, ProviderSubscription.Status.ACTIVE)
        self.assertEqual(ProviderEvent.objects.count(), 2)
        self.assertFalse(ProviderEvent.objects.get(external_event_id="event-old").state_applied)

    def test_purchase_claim_rejects_a_second_account(self):
        self.apply()
        with self.assertRaises(SubscriptionOwnershipError):
            self.apply(account=self.other_admin, event_id="event-2")

    def test_database_constraint_is_the_concurrent_claim_guard(self):
        ProviderSubscription.objects.create(
            account=self.admin,
            provider="apple",
            environment="production",
            external_id="constraint-purchase",
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            ProviderSubscription.objects.create(
                account=self.other_admin,
                provider="apple",
                environment="production",
                external_id="constraint-purchase",
            )

    def test_sandbox_event_does_not_replace_live_legacy_projection(self):
        live_end = self.now + timedelta(days=30)
        self.apply(current_period_end=live_end)
        self.apply(
            environment="sandbox",
            external_id="sandbox-original",
            event_id="sandbox-event",
            latest_transaction_id="sandbox-transaction",
            current_period_end=self.now + timedelta(days=90),
        )

        self.admin.refresh_from_db()
        self.assertEqual(self.admin.subscription_environment, "Production")
        self.assertEqual(self.admin.subscription_ends_at, live_end)


@override_settings(ALLOW_TEST_SUBSCRIPTION_ENTITLEMENTS=False)
class AppleBindingAndSecurityTests(TestCase):
    def setUp(self):
        self.admin = make_admin()
        self.other_admin = make_admin(2)
        self.expires_at = timezone.now() + timedelta(days=30)

    def result(self, admin, **payload_overrides):
        payload = {
            "transactionId": "tx-apple-1",
            "originalTransactionId": "original-apple-1",
            "productId": "de.preismenu.monthly",
            "environment": "Production",
            "expiresDate": str(int(self.expires_at.timestamp() * 1000)),
            "appAccountToken": str(admin.subscription_account_token),
        }
        payload.update(payload_overrides)
        return AppleTransactionResult(payload, "signed", "Production")

    def test_account_token_binds_purchase_and_other_account_cannot_claim_it(self):
        apply_apple_transaction_to_admin(self.admin, self.result(self.admin))

        with self.assertRaises(SubscriptionOwnershipError):
            apply_apple_transaction_to_admin(self.other_admin, self.result(self.admin))

    def test_new_purchase_without_account_token_is_not_first_requester_claimed(self):
        with self.assertRaises(SubscriptionOwnershipError):
            apply_apple_transaction_to_admin(
                self.admin,
                self.result(self.admin, appAccountToken=""),
            )

    def test_legacy_purchase_without_token_requires_existing_same_account_binding(self):
        self.admin.subscription_original_transaction_id = "original-apple-1"
        self.admin.save(update_fields=["subscription_original_transaction_id"])

        apply_apple_transaction_to_admin(
            self.admin,
            self.result(self.admin, appAccountToken=""),
        )

        self.assertEqual(ProviderSubscription.objects.get().account, self.admin)

    @override_settings(APPLE_ROOT_CERTIFICATES_PEM="")
    def test_missing_apple_root_is_not_permissive(self):
        now = timezone.now()
        certificate = SimpleNamespace(
            not_valid_before_utc=now - timedelta(days=1),
            not_valid_after_utc=now + timedelta(days=1),
        )
        with self.assertRaises(SubscriptionConfigurationError):
            _verify_apple_certificate_chain([certificate], require_trusted_root=True)


@override_settings(SECURE_SSL_REDIRECT=False, APPLE_ROOT_CERTIFICATES_PEM="")
class AppleNotificationEndpointTests(APITestCase):
    def test_missing_root_returns_retryable_error_without_state_change(self):
        admin = make_admin()
        with patch(
            "business_menu.views.verify_compact_jws_signature",
            side_effect=SubscriptionConfigurationError("root required"),
        ):
            response = self.client.post(
                "/api/business-menu/admin/subscriptions/apple/notifications/",
                {"signedPayload": "signed.payload.value"},
                format="json",
            )

        self.assertEqual(response.status_code, 503)
        self.assertFalse(response.data["processed"])
        admin.refresh_from_db()
        self.assertEqual(admin.payment_status, "unpaid")
        self.assertFalse(ProviderSubscription.objects.exists())

    def test_invalid_signature_is_acknowledged_without_state_change(self):
        with patch(
            "business_menu.views.verify_compact_jws_signature",
            side_effect=SubscriptionRejectedError("invalid signature"),
        ):
            response = self.client.post(
                "/api/business-menu/admin/subscriptions/apple/notifications/",
                {"signedPayload": "signed.payload.value"},
                format="json",
            )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["processed"])
        self.assertFalse(ProviderSubscription.objects.exists())


class LegacyBackfillTests(TestCase):
    def test_backfill_is_dry_run_by_default_and_idempotent_when_applied(self):
        make_admin(
            payment_status="paid",
            subscription_ends_at=timezone.now() + timedelta(days=20),
            subscription_provider="",
        )
        dry_run = StringIO()
        call_command("backfill_provider_subscriptions", stdout=dry_run)
        self.assertIn("mode=DRY-RUN", dry_run.getvalue())
        self.assertEqual(ProviderSubscription.objects.count(), 0)

        call_command("backfill_provider_subscriptions", "--apply", stdout=StringIO())
        call_command("backfill_provider_subscriptions", "--apply", stdout=StringIO())

        row = ProviderSubscription.objects.get()
        self.assertEqual(row.verification_source, ProviderSubscription.VerificationSource.LEGACY)
        self.assertTrue(row.needs_reconciliation)

    def test_ambiguous_legacy_purchase_is_not_bound_as_verified_apple(self):
        for index in (1, 2):
            make_admin(
                index,
                payment_status="paid",
                subscription_provider="apple",
                subscription_environment="Production",
                subscription_original_transaction_id="duplicated-original",
                subscription_transaction_id="duplicated-transaction",
                subscription_ends_at=timezone.now() + timedelta(days=10),
            )

        call_command("backfill_provider_subscriptions", "--apply", stdout=StringIO())

        rows = list(ProviderSubscription.objects.order_by("account_id"))
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row.provider == "legacy" for row in rows))
        self.assertTrue(all(row.needs_reconciliation for row in rows))
        self.assertTrue(all(not row.latest_transaction_id for row in rows))


@override_settings(
    SECURE_SSL_REDIRECT=False,
    STRIPE_SECRET_KEY="sk_test_123",
    STRIPE_PUBLISHABLE_KEY="pk_test_123",
    STRIPE_WEBHOOK_SECRET="whsec_123",
    STRIPE_PRICE_ID_ANNUAL="price_annual",
    ALLOW_TEST_SUBSCRIPTION_ENTITLEMENTS=False,
)
class StripeSubscriptionWebhookTests(APITestCase):
    def test_checkout_uses_provider_period_and_replay_does_not_extend_it(self):
        admin = make_admin()
        now = timezone.now()
        provider_end = now + timedelta(days=41)
        session = {
            "client_reference_id": str(admin.id),
            "metadata": {},
            "subscription": "sub_123",
            "customer": "cus_123",
        }
        event = SimpleNamespace(
            id="evt_123",
            type="checkout.session.completed",
            created=int(now.timestamp()),
            livemode=True,
            data=SimpleNamespace(object=session),
        )
        first_subscription = {
            "id": "sub_123",
            "status": "active",
            "current_period_end": int(provider_end.timestamp()),
            "cancel_at_period_end": False,
        }
        with patch("stripe.Webhook.construct_event", return_value=event), patch(
            "stripe.Subscription.retrieve",
            return_value=first_subscription,
        ) as retrieve:
            first = self.client.post(
                "/api/business-menu/api/stripe-webhook/",
                data=b"{}",
                content_type="application/json",
                HTTP_STRIPE_SIGNATURE="signature",
            )
            replay = self.client.post(
                "/api/business-menu/api/stripe-webhook/",
                data=b"{}",
                content_type="application/json",
                HTTP_STRIPE_SIGNATURE="signature",
            )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(replay.status_code, 200)
        subscription = ProviderSubscription.objects.get(provider="stripe")
        self.assertEqual(int(subscription.current_period_end.timestamp()), int(provider_end.timestamp()))
        self.assertEqual(ProviderEvent.objects.count(), 1)
        retrieve.assert_called_once_with("sub_123")
