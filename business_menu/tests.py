from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from .models import BusinessAdmin


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
