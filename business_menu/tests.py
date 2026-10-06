from datetime import timedelta
from io import StringIO
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import PasswordResetCode
from .models import BusinessAdmin, Courier, Customer, Order, Payment, Restaurant
from .serializers import BusinessMenuSubscriptionSerializer
from .subscription_services import AppleTransactionResult, SubscriptionConfigurationError, verify_apple_transaction


@override_settings(SECURE_SSL_REDIRECT=False)
class BusinessMenuLoginTests(APITestCase):
    def test_send_otp_returns_json_error_without_404_for_unknown_phone(self):
        for url in ("/api/business-menu/send-otp/", "/api/business-menu/send-otp"):
            response = self.client.post(
                url,
                {"number": "+493012345678"},
                format="json",
            )

            self.assertEqual(response.status_code, 200)
            self.assertFalse(response.data["success"])
            self.assertIn("If this account can be verified", response.data["message"])

    def test_send_otp_finds_admin_by_phone_variant(self):
        admin = BusinessAdmin.objects.create(
            auth_user=User.objects.create_user(username="otp_owner", email="owner@example.com", password="Pass12345"),
            phone="+4915901234567",
            name="QR Menu Admin",
            email="owner@example.com",
            payment_status="trial",
            trial_ends_at=timezone.now() + timedelta(days=1),
        )

        with patch("business_menu.views.send_otp", return_value={"success": True, "message": "sent", "status": "pending"}):
            response = self.client.post(
                "/api/business-menu/send-otp/",
                {"number": "+4915901234567"},
                format="json",
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["phone"], admin.phone)

    def test_login_accepts_legacy_number_and_opcode_payload(self):
        admin = BusinessAdmin.objects.create(
            auth_user=User.objects.create_user(username="otp_owner", email="owner@example.com", password="Pass12345"),
            phone="+4915901234567",
            name="QR Menu Admin",
            email="owner@example.com",
            payment_status="trial",
            trial_ends_at=timezone.now() + timedelta(days=1),
        )
        Restaurant.objects.create(admin=admin, name="Fixture Restaurant")

        with patch("business_menu.views.check_otp", return_value={"success": True, "approved": True}):
            response = self.client.post(
                "/api/business-menu/login/",
                {"number": "+4915901234567", "opCode": "123456"},
                format="json",
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["success"])
        self.assertIn("access", response.data)
        self.assertEqual(response.data["admin"]["id"], admin.id)
        self.assertEqual(response.data["subscription"]["state"], "trial")
        self.assertTrue(response.data["subscription"]["is_entitled"])
        self.assertFalse(response.data["subscription"]["purchasable_in_app"])

    def test_login_accepts_no_slash_url(self):
        admin = BusinessAdmin.objects.create(
            auth_user=User.objects.create_user(username="otp_owner", email="owner@example.com", password="Pass12345"),
            phone="+4915901234567",
            name="QR Menu Admin",
            email="owner@example.com",
            payment_status="trial",
            trial_ends_at=timezone.now() + timedelta(days=1),
        )
        Restaurant.objects.create(admin=admin, name="Fixture Restaurant")

        with patch("business_menu.views.check_otp", return_value={"success": True, "approved": True}):
            response = self.client.post(
                "/api/business-menu/login",
                {"number": "+4915901234567", "opCode": "123456"},
                format="json",
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["admin"]["id"], admin.id)

    def test_login_unknown_phone_returns_json_error_without_404(self):
        response = self.client.post(
            "/api/business-menu/login",
            {"number": "+493012345678", "opCode": "123456"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.data["success"])
        self.assertIn("Invalid", response.data["message"])

    def test_email_login_uses_exactly_linked_user_and_restaurant(self):
        email = "unique@example.com"
        right_user = User.objects.create_user(username="business_admin_492222222222", email=email, password="RightPass123")
        right_admin = BusinessAdmin.objects.create(
            auth_user=right_user, phone="+492222222222", name="Right Admin", email=email,
            payment_status="paid", subscription_ends_at=timezone.now() + timedelta(days=30),
        )
        Restaurant.objects.create(admin=right_admin, name="Fixture Restaurant")
        response = self.client.post(
            "/api/business-menu/login/",
            {"email": email, "password": "RightPass123"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["admin"]["id"], right_admin.id)
        self.assertEqual(response.data["subscription"]["state"], "active")
        self.assertEqual(response.data["subscription"]["provider"], "stripe")
        self.assertTrue(response.data["subscription"]["is_entitled"])

    def test_email_login_returns_token_for_unentitled_admin(self):
        email = "unentitled@example.com"
        user = User.objects.create_user(
            username="business_admin_493333333333",
            email=email,
            password="Pass12345",
        )
        admin = BusinessAdmin.objects.create(
            auth_user=user,
            phone="+493333333333",
            name="Unentitled Admin",
            email=email,
            payment_status="unpaid",
        )
        Restaurant.objects.create(admin=admin, name="Fixture Restaurant")

        response = self.client.post(
            "/api/business-menu/login/",
            {"email": email, "password": "Pass12345"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["success"])
        self.assertIn("access", response.data)
        self.assertEqual(response.data["admin"]["id"], admin.id)
        self.assertEqual(response.data["subscription"]["state"], "none")
        self.assertFalse(response.data["subscription"]["is_entitled"])
        self.assertTrue(response.data["subscription"]["purchasable_in_app"])

    def test_reset_password_response_includes_subscription(self):
        email = "owner@example.com"
        user = User.objects.create_user(
            username="business_admin_4915901234567",
            email=email,
            password="OldStrongPass123!",
        )
        admin = BusinessAdmin.objects.create(
            auth_user=user,
            phone="+4915901234567",
            name="QR Menu Admin",
            email=email,
            payment_status="trial",
            trial_ends_at=timezone.now() + timedelta(days=1),
        )
        Restaurant.objects.create(admin=admin, name="Fixture Restaurant")
        PasswordResetCode.objects.create(
            user=user,
            email=email,
            code="123456",
            expires_at=timezone.now() + timedelta(minutes=10),
        )

        response = self.client.post(
            "/api/business-menu/reset-password/",
            {"email": email, "code": "123456", "password": "NewStrongPass123!"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.data)
        self.assertEqual(response.data["user"]["id"], admin.id)
        self.assertEqual(response.data["subscription"]["state"], "trial")
        self.assertTrue(response.data["subscription"]["is_entitled"])


@override_settings(SECURE_SSL_REDIRECT=False, ALLOW_TEST_SUBSCRIPTION_ENTITLEMENTS=True)
class BusinessMenuSubscriptionEndpointTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="business_admin_4915901234567",
            email="owner@example.com",
            password="Pass12345",
        )
        self.admin = BusinessAdmin.objects.create(
            auth_user=self.user,
            phone="+4915901234567",
            name="QR Menu Admin",
            email="owner@example.com",
            payment_status="trial",
            trial_ends_at=timezone.now() + timedelta(days=1),
        )

    def test_subscription_status_requires_auth_instead_of_404(self):
        response = self.client.get("/api/business-menu/admin/subscription/")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.data["code"], "not_authenticated")
        self.assertIn("no-store", response["Cache-Control"])

    def test_subscription_status_keeps_invalid_and_expired_jwt_as_401_without_logging_tokens(self):
        token = RefreshToken.for_user(self.user).access_token
        token.set_exp(lifetime=timedelta(seconds=-1))
        for invalid in ("invalid.private.token", str(token)):
            with self.subTest(expired=invalid != "invalid.private.token"):
                self.client.credentials(HTTP_AUTHORIZATION="Bearer " + invalid)
                with self.assertLogs("config.drf_exception_handler", level="WARNING") as logs:
                    response = self.client.get("/api/business-menu/admin/subscription/")
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.data["code"], "token_not_valid")
                self.assertIn("authorization_present=True bearer_header=True", " ".join(logs.output))
                self.assertNotIn(invalid, " ".join(logs.output))

    def test_inactive_auth_user_is_not_admitted_by_subscription_status(self):
        token = RefreshToken.for_user(self.user).access_token
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + str(token))

        response = self.client.get("/api/business-menu/admin/subscription/")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.data["code"], "user_inactive")

    def test_invalid_refresh_keeps_401_for_project_refresh_routes(self):
        for url in (
            "/api/business-menu/token/refresh/",
            "/api/business-menu/refresh/",
            "/api/v1/token/refresh/",
            "/api/accounts/token/refresh/",
            "/api/v1/accounts/token/refresh/",
        ):
            with self.subTest(url=url):
                response = self.client.post(url, {"refresh": "invalid.private.refresh"}, format="json")
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.data["code"], "token_not_valid")

    def test_subscription_status_failure_is_temporary_not_a_successful_empty_status(self):
        self.client.force_authenticate(user=self.user)
        with patch("business_menu.serializers.resolve_subscription_entitlement", side_effect=RuntimeError("unavailable")):
            response = self.client.get("/api/business-menu/admin/subscription/")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data["code"], "subscription_status_unavailable")
        self.assertNotIn("is_entitled", response.data)
        self.assertIn("no-store", response["Cache-Control"])

    def test_subscription_status_returns_current_entitlement(self):
        self.client.force_authenticate(user=self.user)

        for method in (self.client.get, self.client.post):
            response = method("/api/business-menu/admin/subscription/")

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data["state"], "trial")
            self.assertTrue(response.data["is_entitled"])
            self.assertFalse(response.data["purchasable_in_app"])

    def test_subscription_status_rejects_inactive_business_account(self):
        self.admin.is_active = False
        self.admin.save(update_fields=["is_active"])
        self.client.force_authenticate(user=self.user)

        response = self.client.get("/api/business-menu/admin/subscription/")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["code"], "account_inactive")

    def test_subscription_status_rejects_inactive_restaurant(self):
        Restaurant.objects.create(admin=self.admin, name="Inactive Restaurant", is_active=False)
        self.client.force_authenticate(user=self.user)

        response = self.client.get("/api/business-menu/admin/subscription/")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["code"], "restaurant_inactive")

    def test_paid_without_period_is_not_entitled(self):
        self.admin.payment_status = "paid"
        self.admin.trial_ends_at = None
        self.admin.subscription_ends_at = None
        self.admin.save(update_fields=["payment_status", "trial_ends_at", "subscription_ends_at"])
        self.client.force_authenticate(user=self.user)

        response = self.client.get("/api/business-menu/admin/subscription/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["state"], "none")
        self.assertIsNone(response.data["provider"])
        self.assertFalse(response.data["is_entitled"])
        self.assertTrue(response.data["purchasable_in_app"])

    def test_manual_subscription_is_entitled(self):
        self.admin.payment_status = "paid"
        self.admin.trial_ends_at = None
        self.admin.subscription_ends_at = timezone.now() + timedelta(days=3650)
        self.admin.subscription_provider = "manual"
        self.admin.subscription_product_id = "manual_pro"
        self.admin.subscription_environment = "manual"
        self.admin.save(
            update_fields=[
                "payment_status",
                "trial_ends_at",
                "subscription_ends_at",
                "subscription_provider",
                "subscription_product_id",
                "subscription_environment",
            ]
        )
        self.client.force_authenticate(user=self.user)

        response = self.client.get("/api/business-menu/admin/subscription/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["state"], "active")
        self.assertEqual(response.data["provider"], "manual")
        self.assertEqual(response.data["plan"], "manual_pro")
        self.assertTrue(response.data["is_entitled"])
        self.assertFalse(response.data["purchasable_in_app"])

    def test_grant_manual_subscription_command_is_idempotent(self):
        Restaurant.objects.create(admin=self.admin, name="Reviewer Bistro")
        out = StringIO()

        call_command(
            "grant_manual_subscription",
            "--email",
            self.admin.email,
            "--expires",
            "2036-12-31",
            stdout=out,
        )
        first_output = out.getvalue()
        self.admin.refresh_from_db()
        first_expires_at = self.admin.subscription_ends_at

        call_command(
            "grant_manual_subscription",
            "--admin-id",
            str(self.admin.id),
            "--expires",
            "2036-12-31",
            stdout=StringIO(),
        )
        self.admin.refresh_from_db()

        self.assertIn(f"admin_id={self.admin.id}", first_output)
        self.assertIn("restaurant_id=", first_output)
        self.assertEqual(self.admin.payment_status, "paid")
        self.assertEqual(self.admin.subscription_provider, "manual")
        self.assertEqual(self.admin.subscription_product_id, "manual_pro")
        self.assertEqual(self.admin.subscription_environment, "manual")
        self.assertEqual(self.admin.subscription_ends_at, first_expires_at)
        self.assertTrue(BusinessMenuSubscriptionSerializer(self.admin).data["is_entitled"])

    def test_subscription_routes_are_registered(self):
        self.client.force_authenticate(user=self.user)

        routes = [
            "/api/business-menu/admin/subscription/apple/verify/",
            "/api/business-menu/admin/subscription/google/verify/",
            "/api/business-menu/admin/subscription/restore/",
        ]
        for route in routes:
            response = self.client.get(route)
            self.assertNotEqual(response.status_code, 404, route)

    def test_store_notification_routes_fail_closed_without_valid_payload_or_configuration(self):
        apple = self.client.post(
            "/api/business-menu/admin/subscriptions/apple/notifications/", {}, format="json"
        )
        google = self.client.post(
            "/api/business-menu/admin/subscriptions/google/notifications/", {}, format="json"
        )

        self.assertEqual(apple.status_code, 200)
        self.assertFalse(apple.data["processed"])
        self.assertEqual(google.status_code, 503)
        self.assertFalse(google.data["processed"])

    @override_settings(
        STRIPE_SECRET_KEY="sk_test_123",
        STRIPE_PUBLISHABLE_KEY="pk_test_123",
        STRIPE_PRICE_ID_ANNUAL="price_123",
    )
    def test_checkout_session_can_be_created_by_account_email(self):
        fake_session = SimpleNamespace(url="https://checkout.stripe.com/c/test", id="cs_test_123")

        with patch("stripe.checkout.Session.create", return_value=fake_session) as create_session:
            response = self.client.post(
                "/api/business-menu/api/create-checkout-session/",
                {"email": self.admin.email},
                format="json",
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["url"], fake_session.url)
        create_session.assert_called_once()

    def test_apple_verify_updates_entitlement(self):
        self.client.force_authenticate(user=self.user)
        expires_at = timezone.now() + timedelta(days=30)
        result = AppleTransactionResult(
            payload={
                "transactionId": "2000000123456789",
                "originalTransactionId": "2000000000000001",
                "productId": "de.preismenu.monthly",
                "environment": "Sandbox",
                "expiresDate": str(int(expires_at.timestamp() * 1000)),
                "appAccountToken": str(self.admin.subscription_account_token),
            },
            signed_transaction_info="signed-from-apple",
            environment="Sandbox",
        )

        with patch("business_menu.views.verify_apple_transaction", return_value=result) as verify:
            response = self.client.post(
                "/api/business-menu/admin/subscription/apple/verify/",
                {
                    "jws": "device.signed.transaction",
                    "product_id": "de.preismenu.monthly",
                    "environment": "Sandbox",
                },
                format="json",
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["subscription"]["state"], "active")
        self.assertEqual(response.data["subscription"]["provider"], "apple")
        self.assertEqual(response.data["subscription"]["plan"], "monthly")
        self.assertFalse(response.data["subscription"]["purchasable_in_app"])
        verify.assert_called_once_with(
            "device.signed.transaction",
            environment="Sandbox",
            expected_product_id="de.preismenu.monthly",
        )
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.payment_status, "paid")
        self.assertEqual(self.admin.subscription_provider, "apple")
        self.assertEqual(self.admin.subscription_product_id, "de.preismenu.monthly")
        self.assertEqual(self.admin.subscription_environment, "Sandbox")
        self.assertEqual(self.admin.subscription_original_transaction_id, "2000000000000001")
        self.assertEqual(self.admin.subscription_transaction_id, "2000000123456789")

    def test_apple_verify_updates_yearly_plan(self):
        self.client.force_authenticate(user=self.user)
        expires_at = timezone.now() + timedelta(days=365)
        result = AppleTransactionResult(
            payload={
                "transactionId": "2000000123456790",
                "originalTransactionId": "2000000000000002",
                "productId": "de.preismenu.yearly",
                "environment": "Sandbox",
                "expiresDate": str(int(expires_at.timestamp() * 1000)),
                "appAccountToken": str(self.admin.subscription_account_token),
            },
            signed_transaction_info="signed-from-apple",
            environment="Sandbox",
        )

        with patch("business_menu.views.verify_apple_transaction", return_value=result):
            response = self.client.post(
                "/api/business-menu/admin/subscription/apple/verify/",
                {
                    "jws": "device.signed.transaction",
                    "product_id": "de.preismenu.yearly",
                    "environment": "Sandbox",
                },
                format="json",
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["subscription"]["plan"], "yearly")
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.subscription_product_id, "de.preismenu.yearly")

    def test_apple_configuration_error_is_stable_and_does_not_leak_details(self):
        self.client.force_authenticate(user=self.user)
        technical_detail = "APPLE_ROOT_CERTIFICATES_PEM is required to trust Apple notifications"

        with patch(
            "business_menu.views.verify_apple_transaction",
            side_effect=SubscriptionConfigurationError(technical_detail),
        ):
            response = self.client.post(
                "/api/business-menu/admin/subscription/apple/verify/",
                {"jws": "device.signed.transaction"},
                format="json",
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data["code"], "subscription_verification_not_configured")
        self.assertNotIn("APPLE_ROOT_CERTIFICATES_PEM", response.data["message"])

    @override_settings(
        APPLE_APP_STORE_ISSUER_ID="issuer",
        APPLE_APP_STORE_KEY_ID="key",
        APPLE_APP_STORE_PRIVATE_KEY="private-key",
        APPLE_APP_BUNDLE_ID="de.preismenu.app",
        APPLE_SUBSCRIPTION_PRODUCT_IDS="de.preismenu.monthly",
    )
    @patch("business_menu.subscription_services.decode_compact_jws_unverified")
    @patch("business_menu.subscription_services._apple_server_jwt")
    @patch("business_menu.subscription_services.requests.get")
    @patch("business_menu.subscription_services.verify_compact_jws_signature")
    def test_apple_transaction_accepts_yearly_even_when_env_lists_monthly(
        self,
        verify_signature,
        requests_get,
        server_jwt,
        decode_unverified,
    ):
        decode_unverified.return_value = ({}, {"transactionId": "2000000123456790", "environment": "Sandbox"})
        server_jwt.return_value = "server-token"
        response = Mock(status_code=200)
        response.json.return_value = {"signedTransactionInfo": "apple.signed.transaction"}
        requests_get.return_value = response
        verify_signature.return_value = {
            "transactionId": "2000000123456790",
            "originalTransactionId": "2000000000000002",
            "bundleId": "de.preismenu.app",
            "productId": "de.preismenu.yearly",
            "environment": "Sandbox",
            "expiresDate": str(int((timezone.now() + timedelta(days=365)).timestamp() * 1000)),
        }

        result = verify_apple_transaction(
            "device.signed.transaction",
            environment="Sandbox",
            expected_product_id="de.preismenu.yearly",
        )

        self.assertEqual(result.payload["productId"], "de.preismenu.yearly")


@override_settings(SECURE_SSL_REDIRECT=False)
class AdminCourierOrderTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="restaurant-admin",
            email="owner@example.com",
            password="Pass12345",
        )
        self.admin = BusinessAdmin.objects.create(
            auth_user=self.user,
            phone="+491700000000",
            name="Restaurant Admin",
            email="owner@example.com",
            payment_status="paid",
        )
        self.restaurant = Restaurant.objects.create(
            admin=self.admin,
            name="Test Bistro",
        )
        self.client.force_authenticate(user=self.user)

    def test_courier_crud_and_delete_without_history(self):
        create_response = self.client.post(
            "/api/business-menu/admin/couriers/",
            {"name": "Ali Yildiz", "phone": "+491701112233", "is_active": True},
            format="json",
        )
        self.assertEqual(create_response.status_code, 201)
        courier_id = create_response.data["id"]

        list_response = self.client.get("/api/business-menu/admin/couriers/")
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(list_response.data["count"], 1)

        patch_response = self.client.patch(
            f"/api/business-menu/admin/couriers/{courier_id}/",
            {"is_active": False},
            format="json",
        )
        self.assertEqual(patch_response.status_code, 200)
        self.assertFalse(patch_response.data["is_active"])

        delete_response = self.client.delete(f"/api/business-menu/admin/couriers/{courier_id}/")
        self.assertEqual(delete_response.status_code, 204)

        list_after_delete = self.client.get("/api/business-menu/admin/couriers/")
        self.assertEqual(list_after_delete.status_code, 200)
        self.assertEqual(list_after_delete.data, {"count": 0, "couriers": []})

        repeated_delete = self.client.delete(f"/api/business-menu/admin/couriers/{courier_id}/")
        self.assertEqual(repeated_delete.status_code, 404)
        self.assertEqual(repeated_delete.data["code"], "courier_not_found")

    def test_delete_courier_with_completed_order_archives_and_preserves_history(self):
        courier = Courier.objects.create(
            restaurant=self.restaurant,
            name="Ali Yildiz",
            phone="+491701112233",
        )
        order = Order.objects.create(
            restaurant=self.restaurant,
            courier=courier,
            status=Order.Status.COMPLETED,
            service_type=Order.ServiceType.DELIVERY,
            total_amount="25.00",
            items_json=[{"name": "Pizza", "quantity": 1}],
        )
        payment = Payment.objects.create(
            restaurant=self.restaurant,
            order=order,
            amount="25.00",
            currency="EUR",
            status=Payment.Status.SUCCEEDED,
        )

        response = self.client.delete(f"/api/business-menu/admin/couriers/{courier.id}/")

        self.assertEqual(response.status_code, 204)
        courier.refresh_from_db()
        order.refresh_from_db()
        payment.refresh_from_db()
        self.assertFalse(courier.is_active)
        self.assertEqual(order.courier_id, courier.id)
        self.assertEqual(str(order.total_amount), "25.00")
        self.assertEqual(str(payment.amount), "25.00")

        list_response = self.client.get("/api/business-menu/admin/couriers/")
        self.assertEqual(list_response.data, {"count": 0, "couriers": []})

        orders_response = self.client.get("/api/business-menu/admin/orders/")
        historical_order = next(item for item in orders_response.data["orders"] if item["id"] == order.id)
        self.assertEqual(historical_order["courier"], courier.id)
        self.assertEqual(historical_order["courier_name"], "Ali Yildiz")
        self.assertEqual(historical_order["courier_phone"], "+491701112233")

        new_order = Order.objects.create(
            restaurant=self.restaurant,
            status=Order.Status.PREPARING,
            service_type=Order.ServiceType.DELIVERY,
        )
        assign_response = self.client.post(
            f"/api/business-menu/admin/orders/{new_order.id}/assign-courier/",
            {"courier_id": courier.id},
            format="json",
        )
        self.assertEqual(assign_response.status_code, 404)

        repeated_delete = self.client.delete(f"/api/business-menu/admin/couriers/{courier.id}/")
        self.assertEqual(repeated_delete.status_code, 204)
        self.assertTrue(Courier.objects.filter(pk=courier.id, is_active=False).exists())

    def test_delete_courier_with_current_order_returns_clear_409(self):
        courier = Courier.objects.create(
            restaurant=self.restaurant,
            name="Ali Yildiz",
            phone="+491701112233",
        )
        order = Order.objects.create(
            restaurant=self.restaurant,
            courier=courier,
            status=Order.Status.OUT_FOR_DELIVERY,
            service_type=Order.ServiceType.DELIVERY,
        )

        response = self.client.delete(f"/api/business-menu/admin/couriers/{courier.id}/")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "courier_has_current_order")
        self.assertEqual(
            response.data["detail"],
            "Courier is assigned to a current order and cannot be removed.",
        )
        courier.refresh_from_db()
        order.refresh_from_db()
        self.assertTrue(courier.is_active)
        self.assertEqual(order.courier_id, courier.id)

    def test_other_restaurant_cannot_delete_courier(self):
        other_user = User.objects.create_user("other-restaurant", password="Pass12345")
        other_admin = BusinessAdmin.objects.create(
            auth_user=other_user,
            phone="+491700000099",
            name="Other Restaurant Admin",
            email="other-owner@example.com",
            payment_status="paid",
        )
        other_restaurant = Restaurant.objects.create(admin=other_admin, name="Other Bistro")
        other_courier = Courier.objects.create(
            restaurant=other_restaurant,
            name="Other Courier",
            phone="+491701119999",
        )

        response = self.client.delete(f"/api/business-menu/admin/couriers/{other_courier.id}/")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data["code"], "courier_not_found")
        other_courier.refresh_from_db()
        self.assertTrue(other_courier.is_active)

    def test_assign_courier_sets_out_for_delivery_atomically(self):
        courier = Courier.objects.create(
            restaurant=self.restaurant,
            name="Ali Yildiz",
            phone="+491701112233",
        )
        order = Order.objects.create(
            restaurant=self.restaurant,
            status=Order.Status.PREPARING,
            service_type=Order.ServiceType.DELIVERY,
        )

        response = self.client.post(
            f"/api/business-menu/admin/orders/{order.id}/assign-courier/",
            {"courier_id": courier.id},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], Order.Status.OUT_FOR_DELIVERY)
        self.assertEqual(response.data["courier"], courier.id)
        self.assertEqual(response.data["courier_name"], "Ali Yildiz")
        self.assertTrue(response.data["actions"]["can_mark_completed"])
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.OUT_FOR_DELIVERY)
        self.assertEqual(order.courier_id, courier.id)

    def test_assign_courier_rejects_non_delivery_order(self):
        courier = Courier.objects.create(
            restaurant=self.restaurant,
            name="Ali Yildiz",
            phone="+491701112233",
        )
        order = Order.objects.create(
            restaurant=self.restaurant,
            status=Order.Status.PREPARING,
            service_type=Order.ServiceType.PICKUP,
        )

        response = self.client.post(
            f"/api/business-menu/admin/orders/{order.id}/assign-courier/",
            {"courier_id": courier.id},
            format="json",
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["detail"], "pickup_orders_do_not_use_a_courier")

    def test_patch_order_cancelled_stores_optional_reason(self):
        order = Order.objects.create(
            restaurant=self.restaurant,
            status=Order.Status.PREPARING,
            service_type=Order.ServiceType.DELIVERY,
        )

        response = self.client.patch(
            f"/api/business-menu/admin/orders/{order.id}/",
            {"status": "cancelled", "reason": "customer_no_show"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], Order.Status.CANCELLED)
        self.assertEqual(response.data["cancellation_reason"], "customer_no_show")

    @override_settings(STRIPE_SECRET_KEY="sk_test_123")
    def test_public_cancel_online_order_refunds_stripe(self):
        self.admin.stripe_account_id = "acct_123"
        self.admin.save(update_fields=["stripe_account_id"])
        customer = Customer.objects.create(
            restaurant=self.restaurant,
            phone="+491701112233",
            name="Ali Asadi",
        )
        order = Order.objects.create(
            restaurant=self.restaurant,
            customer=customer,
            status=Order.Status.PAID,
            service_type=Order.ServiceType.DELIVERY,
            payment_method=Order.PaymentMethod.ONLINE,
            total_amount="25.00",
            stripe_payment_intent_id="pi_123",
        )
        Payment.objects.create(
            restaurant=self.restaurant,
            order=order,
            stripe_payment_intent_id="pi_123",
            amount="25.00",
            currency="EUR",
            status=Payment.Status.SUCCEEDED,
        )
        refund_create = Mock(
            return_value={"id": "re_123", "status": "succeeded", "amount": 2500}
        )
        fake_stripe = SimpleNamespace(
            api_key="",
            Refund=SimpleNamespace(create=refund_create),
        )

        with patch.dict("sys.modules", {"stripe": fake_stripe}):
            response = self.client.post(
                f"/api/business-menu/orders/{order.id}/cancel/",
                {
                    "restaurant_id": self.restaurant.id,
                    "phone": "+491701112233",
                    "reason": "customer_cancelled",
                },
                format="json",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], Order.Status.REFUNDED)
        self.assertEqual(response.data["refund"]["refund_id"], "re_123")
        self.assertEqual(response.data["refund"]["status"], "succeeded")
        refund_create.assert_called_once()
        _, kwargs = refund_create.call_args
        self.assertEqual(kwargs["payment_intent"], "pi_123")
        self.assertTrue(kwargs["reverse_transfer"])
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.REFUNDED)

        admin_response = self.client.get("/api/business-menu/admin/orders/")
        self.assertEqual(admin_response.status_code, 200)
        admin_order = next(o for o in admin_response.data["orders"] if o["id"] == order.id)
        self.assertEqual(admin_order["status"], Order.Status.REFUNDED)
        self.assertTrue(admin_order["is_cancelled"])
        self.assertFalse(admin_order["actions"]["can_cancel"])
        self.assertEqual(admin_order["refund"]["refund_id"], "re_123")
        self.assertEqual(admin_order["payment"]["refund"]["status"], "succeeded")

    def test_public_cancel_rejects_out_for_delivery_order(self):
        customer = Customer.objects.create(
            restaurant=self.restaurant,
            phone="+491701112233",
            name="Ali Asadi",
        )
        order = Order.objects.create(
            restaurant=self.restaurant,
            customer=customer,
            status=Order.Status.OUT_FOR_DELIVERY,
            service_type=Order.ServiceType.DELIVERY,
            payment_method=Order.PaymentMethod.ONLINE,
            total_amount="25.00",
            stripe_payment_intent_id="pi_123",
        )

        response = self.client.post(
            f"/api/business-menu/orders/{order.id}/cancel/",
            {
                "restaurant_id": self.restaurant.id,
                "phone": "+491701112233",
                "reason": "customer_cancelled",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["detail"], "invalid_transition")
