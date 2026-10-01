from unittest.mock import patch

from django.test import override_settings
from rest_framework.test import APITestCase

from accounts.models import MenuCustomer
from business_menu.customer_auth import SESSION_KEY
from business_menu.models import BusinessAdmin, Customer, Order, Payment, Restaurant, RestaurantSettings
from business_menu.stripe_views import _record_order_payment_success


@override_settings(
    SECURE_SSL_REDIRECT=False,
    STRIPE_SECRET_KEY="sk_test_local",
    STRIPE_PUBLISHABLE_KEY="pk_test_local",
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
)
class OrderCustomerFlowTests(APITestCase):
    def setUp(self):
        admin = BusinessAdmin.objects.create(phone="+491700001111", name="Owner")
        self.restaurant = Restaurant.objects.create(admin=admin, name="Flow Bistro")
        RestaurantSettings.objects.update_or_create(
            restaurant=self.restaurant,
            defaults={
            "has_delivery": True,
            "delivery_enabled": True,
            "allow_payment_cash": True,
            "allow_payment_online": True,
            "opening_hours_json": [],
            },
        )
        session = self.client.session
        session.save()
        self.session_key = session.session_key

    def _cart(self):
        session = self.client.session
        session[f"cart_restaurant_{self.restaurant.id}"] = [
            {"menu_item_id": 1, "name": "Soup", "price": "12.50", "quantity": 1}
        ]
        session.save()

    def _create_online(self, service_type):
        self._cart()
        payload = {
            "restaurant_id": self.restaurant.id,
            "service_type": service_type,
            "payment_method": "online",
        }
        if service_type == "dine_in":
            payload["table_number"] = "7"
        if service_type == "delivery":
            payload.update(customer_phone="+491700009999", customer_address="Main Street 1")
        return self.client.post("/api/business-menu/orders/", payload, format="json")

    def _paid_order(self, service_type="pickup"):
        order = Order.objects.create(
            restaurant=self.restaurant,
            status=Order.Status.PAID,
            service_type=service_type,
            payment_method=Order.PaymentMethod.ONLINE,
            session_key=self.session_key,
            total_amount="12.50",
            stripe_payment_intent_id="pi_verified",
        )
        Payment.objects.create(
            restaurant=self.restaurant,
            order=order,
            stripe_payment_intent_id="pi_verified",
            amount=order.total_amount,
            status=Payment.Status.SUCCEEDED,
        )
        return order

    def _details(self, order, **updates):
        payload = {
            "restaurant_id": self.restaurant.id,
            "order_id": order.id,
            "first_name": "Ada",
            "last_name": "Lovelace",
            "email": "ada@example.com",
            "phone": "+491700002222",
        }
        payload.update(updates)
        return self.client.post("/api/business-menu/orders/finalize-paid/", payload, format="json")

    def test_all_online_service_types_are_preserved_and_profile_is_deferred(self):
        for service_type in ("pickup", "dine_in", "delivery"):
            response = self._create_online(service_type)
            self.assertEqual(response.status_code, 201, response.data)
            order = Order.objects.get(pk=response.data["order_id"])
            self.assertEqual(order.service_type, service_type)
            self.assertIsNone(order.customer_id)

    @patch("business_menu.invoice_email.send_invoice_email_async")
    def test_cash_pickup_and_dine_in_do_not_require_an_account(self, send_invoice):
        for service_type in ("pickup", "dine_in"):
            self._cart()
            payload = {
                "restaurant_id": self.restaurant.id,
                "service_type": service_type,
                "payment_method": "cash",
            }
            if service_type == "dine_in":
                payload["table_number"] = "7"
            response = self.client.post("/api/business-menu/orders/", payload, format="json")
            self.assertEqual(response.status_code, 201, response.data)
            self.assertIsNone(Order.objects.get(pk=response.data["order_id"]).customer_id)
        send_invoice.assert_not_called()

    def test_unverified_payment_and_foreign_session_cannot_finalize(self):
        order = Order.objects.create(
            restaurant=self.restaurant,
            service_type=Order.ServiceType.PICKUP,
            payment_method=Order.PaymentMethod.ONLINE,
            session_key=self.session_key,
        )
        response = self._details(order)
        self.assertEqual(response.status_code, 400)

        other = self.client_class()
        response = other.post(
            "/api/business-menu/orders/finalize-paid/",
            {"restaurant_id": self.restaurant.id, "order_id": order.id, "first_name": "A", "last_name": "B", "email": "a@b.co", "phone": "+491700003333"},
            format="json",
        )
        self.assertEqual(response.status_code, 404)

    @patch("business_menu.customer_auth.send_customer_password_reset_code", return_value=True)
    @patch("business_menu.invoice_email.send_invoice_email_async")
    def test_repeat_finalize_creates_one_account_customer_and_invoice(self, send_invoice, _send_code):
        order = self._paid_order()
        with self.captureOnCommitCallbacks(execute=True):
            first = self._details(order)
            second = self._details(order)
        self.assertEqual(first.status_code, 200, first.data)
        self.assertEqual(second.status_code, 200, second.data)
        self.assertEqual(first.data["tracking_url"], f"/restaurants/{self.restaurant.id}/orders/?order={order.id}")
        self.assertEqual(MenuCustomer.objects.filter(email="ada@example.com").count(), 1)
        self.assertEqual(order.payments.count(), 1)
        self.assertEqual(send_invoice.call_count, 1)
        self.assertNotIn(SESSION_KEY, self.client.session)

    @patch("business_menu.invoice_email.send_invoice_email_async")
    def test_existing_email_is_not_logged_in_or_attached(self, _send_invoice):
        existing = MenuCustomer(email="ada@example.com", phone="+491700004444")
        existing.set_password("safe-password")
        existing.save()
        response = self._details(self._paid_order())
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["account_status"], "login_required")
        self.assertNotIn(SESSION_KEY, self.client.session)
        existing.refresh_from_db()
        self.assertTrue(existing.check_password("safe-password"))

    @patch("business_menu.invoice_email.send_invoice_email_async")
    def test_logged_in_complete_customer_finalizes_without_new_account(self, _send_invoice):
        customer = MenuCustomer(email="member@example.com", phone="+491700005555", first_name="Full", last_name="Member")
        customer.set_password("safe-password")
        customer.save()
        session = self.client.session
        session[SESSION_KEY] = customer.id
        session.save()
        order = self._paid_order()
        response = self.client.post(
            "/api/business-menu/orders/finalize-paid/",
            {"restaurant_id": self.restaurant.id, "order_id": order.id},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["account_status"], "authenticated")
        self.assertEqual(MenuCustomer.objects.count(), 1)

    def test_duplicate_verified_webhook_record_is_idempotent(self):
        order = Order.objects.create(
            restaurant=self.restaurant,
            service_type=Order.ServiceType.DINE_IN,
            payment_method=Order.PaymentMethod.ONLINE,
            session_key=self.session_key,
            total_amount="12.50",
        )
        _record_order_payment_success(order, "pi_once", "ch_once")
        _record_order_payment_success(order, "pi_once", "ch_once")
        self.assertEqual(Payment.objects.filter(order=order).count(), 1)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PAID)
        self.assertEqual(order.service_type, Order.ServiceType.DINE_IN)

    def test_success_query_parameter_does_not_claim_payment(self):
        order = Order.objects.create(
            restaurant=self.restaurant,
            service_type=Order.ServiceType.PICKUP,
            payment_method=Order.PaymentMethod.ONLINE,
            session_key=self.session_key,
        )
        response = self.client.get(f"/restaurants/{self.restaurant.id}/order/{order.id}/pay/?payment=success")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Payment received")

    def test_selected_order_status_is_exact_and_session_scoped(self):
        older = Order.objects.create(
            restaurant=self.restaurant,
            session_key=self.session_key,
            payment_method=Order.PaymentMethod.CASH,
            total_amount="8.00",
        )
        selected = Order.objects.create(
            restaurant=self.restaurant,
            session_key=self.session_key,
            payment_method=Order.PaymentMethod.CASH,
            total_amount="12.00",
        )
        response = self.client.get(
            "/api/business-menu/orders/list/",
            {"restaurant_id": self.restaurant.id, "order_id": selected.id},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual([order["id"] for order in response.data["orders"]], [selected.id])
        self.assertNotEqual(older.id, selected.id)

        guest = self.client_class()
        self.assertEqual(guest.get("/api/business-menu/customer/me/").status_code, 401)
        denied = guest.get(
            "/api/business-menu/orders/list/",
            {"restaurant_id": self.restaurant.id, "order_id": selected.id},
        )
        self.assertEqual(denied.status_code, 200)
        self.assertEqual(denied.data["orders"], [])

        tracker = self.client.get(f"/restaurants/{self.restaurant.id}/orders/?order={selected.id}")
        self.assertEqual(tracker.status_code, 200)
        self.assertContains(tracker, "selectedOrderId")
        self.assertContains(tracker, "window.setInterval")
        self.assertNotContains(tracker, "window.location.href =")
        self.assertNotContains(tracker, "window.location.replace(")

    def test_logged_in_customer_can_reopen_their_exact_order(self):
        crm_customer = Customer.objects.create(
            restaurant=self.restaurant,
            business_admin=self.restaurant.admin,
            phone="+491700006666",
        )
        order = Order.objects.create(
            restaurant=self.restaurant,
            customer=crm_customer,
            session_key="another-browser-session",
            payment_method=Order.PaymentMethod.CASH,
        )
        menu_customer = MenuCustomer.objects.create(
            email="member-status@example.com",
            phone="+491700006666",
        )
        session = self.client.session
        session[SESSION_KEY] = menu_customer.id
        session.save()

        response = self.client.get(
            "/api/business-menu/orders/list/",
            {"restaurant_id": self.restaurant.id, "order_id": order.id},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.data["orders"]], [order.id])
