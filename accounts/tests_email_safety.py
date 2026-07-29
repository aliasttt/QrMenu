from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from accounts.models import EmailVerificationCode, MenuCustomer, PasswordResetCode
from business_menu.invoice_email import send_invoice_email_async
from business_menu.models import BusinessAdmin, Customer, Order, Restaurant


EMAIL_TEST_SETTINGS = dict(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="qrmenu@mybonusberlin.com",
    BONUS_FROM_EMAIL="qrmenu@mybonusberlin.com",
    CONTACT_ADMIN_EMAIL="qrmenu@mybonusberlin.com",
    EMAIL_ACTION_COOLDOWN_SECONDS=0,
    EMAIL_GLOBAL_SAFETY_LIMIT=1000,
    SECURE_SSL_REDIRECT=False,
)


@override_settings(**EMAIL_TEST_SETTINGS)
class EmailSafetyAPITests(APITestCase):
    def setUp(self):
        cache.clear()
        mail.outbox = []
        self.user = User.objects.create_user(
            username="user_491700000000",
            email="user@example.com",
            password="Pass12345",
        )

    def test_legitimate_verification_email_works(self):
        response = self.client.post(
            "/api/accounts/send-email-code/",
            {"email": "USER@example.com", "user_id": self.user.id},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["user@example.com"])
        self.assertEqual(EmailVerificationCode.objects.filter(email="user@example.com").count(), 1)

    def test_repeated_verification_requests_are_blocked(self):
        for _ in range(3):
            self.client.post(
                "/api/accounts/send-email-code/",
                {"email": "user@example.com", "user_id": self.user.id},
                format="json",
            )

        response = self.client.post(
            "/api/accounts/send-email-code/",
            {"email": "user@example.com", "user_id": self.user.id},
            format="json",
        )

        self.assertEqual(response.status_code, 429)
        self.assertEqual(len(mail.outbox), 3)

    def test_password_reset_unknown_email_is_generic_and_sends_no_email(self):
        response = self.client.post(
            "/api/accounts/password/forgot/",
            {"email": "unknown@example.com"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("detail", response.data)
        self.assertEqual(len(mail.outbox), 0)

    def test_repeated_password_reset_requests_are_blocked(self):
        for _ in range(3):
            self.client.post(
                "/api/accounts/password/forgot/",
                {"email": "user@example.com"},
                format="json",
            )

        response = self.client.post(
            "/api/accounts/password/forgot/",
            {"email": "user@example.com"},
            format="json",
        )

        self.assertEqual(response.status_code, 429)
        self.assertEqual(len(mail.outbox), 3)

    def test_limits_use_normalized_email(self):
        for email in ("User@Example.com", " user@example.com ", "USER@example.COM"):
            self.client.post(
                "/api/accounts/send-email-code/",
                {"email": email, "user_id": self.user.id},
                format="json",
            )

        response = self.client.post(
            "/api/accounts/send-email-code/",
            {"email": "user@example.com", "user_id": self.user.id},
            format="json",
        )

        self.assertEqual(response.status_code, 429)
        self.assertEqual(len(mail.outbox), 3)

    def test_recipient_cannot_be_controlled_through_request_data(self):
        response = self.client.post(
            "/api/accounts/send-email-code/",
            {"email": "attacker@example.com", "user_id": self.user.id},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)

    def test_mobile_send_otp_still_functions_and_uses_account_email(self):
        from accounts.models import Profile

        profile, _ = Profile.objects.get_or_create(user=self.user)
        profile.phone = "+491700000000"
        profile.phone_verified = True
        profile.save(update_fields=["phone", "phone_verified"])
        with patch("accounts.views.send_otp", return_value={"success": True, "message": "sent", "status": "pending"}):
            response = self.client.post(
                "/api/accounts/send-otp/",
                {"phone": "+491700000000"},
                format="json",
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["success"])
        self.assertEqual(mail.outbox[0].to, ["user@example.com"])


@override_settings(**EMAIL_TEST_SETTINGS)
class ContactSafetyTests(TestCase):
    def setUp(self):
        cache.clear()
        mail.outbox = []

    def test_contact_honeypot_sends_no_email(self):
        response = self.client.post(
            "/contact/",
            {
                "name": "Test User",
                "email": "user@example.com",
                "subject": "Help",
                "message": "Hello",
                "website": "https://spam.example",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(TURNSTILE_SECRET_KEY="secret")
    @patch("accounts.email_safety.requests.post")
    def test_invalid_turnstile_sends_no_email(self, post_mock):
        post_mock.return_value.ok = True
        post_mock.return_value.json.return_value = {"success": False}

        response = self.client.post(
            "/contact/",
            {
                "name": "Test User",
                "email": "user@example.com",
                "subject": "Help",
                "message": "Hello",
                "cf-turnstile-response": "bad",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(len(mail.outbox), 0)


@override_settings(**EMAIL_TEST_SETTINGS)
class DuplicateEmailTaskTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(username="owner", email="owner@example.com", password="Pass12345")
        self.admin = BusinessAdmin.objects.create(
            auth_user=self.user,
            phone="+491700000001",
            name="Owner",
            email="owner@example.com",
            payment_status="paid",
            trial_ends_at=timezone.now() + timedelta(days=1),
        )
        self.restaurant = Restaurant.objects.create(admin=self.admin, name="Test Bistro")
        self.customer = Customer.objects.create(
            restaurant=self.restaurant,
            phone="+491700000002",
            name="Customer",
            email="customer@example.com",
        )
        self.order = Order.objects.create(
            restaurant=self.restaurant,
            customer=self.customer,
            status=Order.Status.PAID,
            service_type=Order.ServiceType.PICKUP,
            payment_method=Order.PaymentMethod.CASH,
            total_amount="10.00",
        )

    @patch("business_menu.invoice_email.send_invoice_email")
    def test_duplicate_invoice_task_is_not_created(self, send_mock):
        send_invoice_email_async(self.order.id)
        send_invoice_email_async(self.order.id)

        self.assertEqual(send_mock.call_count, 1)
