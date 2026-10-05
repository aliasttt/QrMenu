from unittest.mock import patch

import requests
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient


@override_settings(
    SECURE_SSL_REDIRECT=False,
    RECAPTCHA_SITE_KEY="recaptcha-public-test",
    RECAPTCHA_SECRET_KEY="recaptcha-secret-test",
    TURNSTILE_SITE_KEY="turnstile-public-test",
    TURNSTILE_SECRET_KEY="turnstile-secret-test",
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
)
class SignupCaptchaTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.signup = {
            "restaurant_name": "Captcha Test Cafe",
            "email": "captcha-signup@example.test",
            "phone": "+49305550042",
            "password": "a-strong-test-password-42",
            "accept_terms": True,
            "b2b_confirmation": True,
            "captcha_token": "recaptcha-response-test",
            "turnstile_token": "turnstile-response-test",
        }

    def test_register_page_renders_both_configured_providers_and_success_callbacks(self):
        response = self.client.get("/auth/register/?source=app")
        html = response.content.decode()
        self.assertEqual(response.status_code, 200)
        self.assertIn('class="g-recaptcha"', html)
        self.assertIn('data-callback="signupRecaptchaVerified"', html)
        self.assertIn('class="cf-turnstile"', html)
        self.assertIn('data-callback="signupTurnstileVerified"', html)
        self.assertIn('name="source" value="app"', html)
        self.assertIn('body.captcha_token = captchaTokens.recaptcha', html)
        self.assertIn('body.turnstile_token = captchaTokens.turnstile', html)

    def test_both_valid_responses_are_verified_and_signup_continues(self):
        with (
            patch("business_menu.views.verify_captcha_response", side_effect=[(True, "verified"), (True, "verified")]) as verify,
            patch("business_menu.views._send_signup_verification_email", return_value=True),
        ):
            response = self.client.post("/api/business-menu/signup/", self.signup, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["email_verification_required"])
        self.assertEqual(verify.call_args_list[0].args, ("turnstile", "turnstile-response-test"))
        self.assertEqual(verify.call_args_list[1].args, ("recaptcha", "recaptcha-response-test"))

    def test_missing_turnstile_token_is_reported_before_signup(self):
        self.signup.pop("turnstile_token")
        with patch("business_menu.views.verify_captcha_response", return_value=(False, "missing_token")) as verify:
            response = self.client.post("/api/business-menu/signup/", self.signup, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "captcha_turnstile_missing_token")
        verify.assert_called_once_with("turnstile", "", remoteip="127.0.0.1")

    def test_recaptcha_rejection_is_distinguished_after_turnstile_passes(self):
        with patch(
            "business_menu.views.verify_captcha_response",
            side_effect=[(True, "verified"), (False, "expired_or_duplicate")],
        ):
            response = self.client.post("/api/business-menu/signup/", self.signup, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "captcha_recaptcha_expired_or_duplicate")

    def test_provider_outage_returns_service_unavailable_code(self):
        with patch(
            "business_menu.views.verify_captcha_response",
            return_value=(False, "network_error"),
        ):
            response = self.client.post("/api/business-menu/signup/", self.signup, format="json")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["code"], "captcha_turnstile_network_error")


@override_settings(
    RECAPTCHA_SECRET_KEY="recaptcha-secret-test",
    TURNSTILE_SECRET_KEY="turnstile-secret-test",
)
class CaptchaProviderResultTests(SimpleTestCase):
    def verify(self, token="captcha-response-test", provider="turnstile"):
        from accounts.email_safety import verify_captcha_response

        return verify_captcha_response(provider, token)

    def test_empty_token_does_not_call_provider(self):
        with patch("accounts.email_safety.requests.post") as post:
            self.assertEqual(self.verify(""), (False, "missing_token"))
        post.assert_not_called()

    def test_timeout_or_duplicate_is_reported_without_exposing_token(self):
        response = type("Response", (), {"ok": True, "json": lambda self: {"success": False, "error-codes": ["timeout-or-duplicate"]}})()
        with patch("accounts.email_safety.requests.post", return_value=response):
            result = self.verify()
        self.assertEqual(result, (False, "expired_or_duplicate"))

    def test_provider_configuration_and_network_failures_are_distinct(self):
        invalid_secret = type("Response", (), {"ok": True, "json": lambda self: {"success": False, "error-codes": ["invalid-input-secret"]}})()
        with patch("accounts.email_safety.requests.post", return_value=invalid_secret):
            self.assertEqual(self.verify(), (False, "configuration_error"))
        with patch("accounts.email_safety.requests.post", side_effect=requests.Timeout):
            self.assertEqual(self.verify(), (False, "network_error"))

    def test_verified_provider_response_succeeds(self):
        response = type("Response", (), {"ok": True, "json": lambda self: {"success": True}})()
        with patch("accounts.email_safety.requests.post", return_value=response):
            self.assertEqual(self.verify(), (True, "verified"))
