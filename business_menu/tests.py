from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.contrib.auth.models import User
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from accounts.models import PasswordResetCode
from .models import BusinessAdmin, Courier, Customer, Order, Payment, Restaurant


@override_settings(SECURE_SSL_REDIRECT=False)
class BusinessMenuLoginTests(APITestCase):
    def test_send_otp_returns_json_error_without_404_for_unknown_phone(self):
        for url in ("/api/business-menu/send-otp/", "/api/business-menu/send-otp"):
            response = self.client.post(
                url,
                {"number": "5350382335"},
                format="json",
            )

            self.assertEqual(response.status_code, 200)
            self.assertFalse(response.data["success"])
            self.assertIn("not registered", response.data["message"])

    def test_send_otp_finds_admin_by_phone_variant(self):
        admin = BusinessAdmin.objects.create(
            phone="+4915901234567",
            name="QR Menu Admin",
            email="owner@example.com",
            payment_status="trial",
            trial_ends_at=timezone.now() + timedelta(days=1),
        )

        with patch("business_menu.views.send_otp", return_value={"success": True, "message": "sent", "status": "pending"}):
            response = self.client.post(
                "/api/business-menu/send-otp/",
                {"number": "015901234567"},
                format="json",
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["phone"], admin.phone)

    def test_login_accepts_legacy_number_and_opcode_payload(self):
        admin = BusinessAdmin.objects.create(
            phone="+4915901234567",
            name="QR Menu Admin",
            email="owner@example.com",
            payment_status="trial",
            trial_ends_at=timezone.now() + timedelta(days=1),
        )

        with patch("business_menu.views.check_otp", return_value={"success": True, "approved": True}):
            response = self.client.post(
                "/api/business-menu/login/",
                {"number": "015901234567", "opCode": "123456"},
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
            phone="+4915901234567",
            name="QR Menu Admin",
            email="owner@example.com",
            payment_status="trial",
            trial_ends_at=timezone.now() + timedelta(days=1),
        )

        with patch("business_menu.views.check_otp", return_value={"success": True, "approved": True}):
            response = self.client.post(
                "/api/business-menu/login",
                {"number": "015901234567", "opCode": "123456"},
                format="json",
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["admin"]["id"], admin.id)

    def test_login_unknown_phone_returns_json_error_without_404(self):
        response = self.client.post(
            "/api/business-menu/login",
            {"number": "5350382335", "opCode": "123456"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["success"])
        self.assertIn("not registered", response.data["message"])

    def test_email_login_uses_admin_whose_linked_user_password_matches(self):
        email = "duplicate@example.com"
        wrong_user = User.objects.create_user(
            username="business_admin_491111111111",
            email=email,
            password="WrongPass123",
        )
        wrong_admin = BusinessAdmin.objects.create(
            auth_user=wrong_user,
            phone="+491111111111",
            name="Wrong Admin",
            email=email,
            payment_status="paid",
        )
        right_user = User.objects.create_user(
            username="business_admin_492222222222",
            email=email,
            password="RightPass123",
        )
        right_admin = BusinessAdmin.objects.create(
            auth_user=right_user,
            phone="+492222222222",
            name="Right Admin",
            email=email,
            payment_status="paid",
        )

        response = self.client.post(
            "/api/business-menu/login/",
            {"email": email, "password": "RightPass123"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["admin"]["id"], right_admin.id)
        self.assertNotEqual(response.data["admin"]["id"], wrong_admin.id)
        self.assertEqual(response.data["subscription"]["state"], "active")
        self.assertEqual(response.data["subscription"]["provider"], "stripe")
        self.assertTrue(response.data["subscription"]["is_entitled"])

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

    def test_delete_courier_with_order_history_returns_409(self):
        courier = Courier.objects.create(
            restaurant=self.restaurant,
            name="Ali Yildiz",
            phone="+491701112233",
        )
        Order.objects.create(
            restaurant=self.restaurant,
            courier=courier,
            status=Order.Status.OUT_FOR_DELIVERY,
            service_type=Order.ServiceType.DELIVERY,
        )

        response = self.client.delete(f"/api/business-menu/admin/couriers/{courier.id}/")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["detail"], "courier_has_order_history")

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
