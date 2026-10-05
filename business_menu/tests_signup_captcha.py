import json
from unittest.mock import patch

import requests
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils.translation import gettext, override
from rest_framework.test import APIClient


@override_settings(
    SECURE_SSL_REDIRECT=False,
    # Keep Google configured in tests to prove signup no longer depends on it.
    RECAPTCHA_SITE_KEY="recaptcha-public-test",
    RECAPTCHA_SECRET_KEY="recaptcha-secret-test",
    TURNSTILE_SITE_KEY="turnstile-public-test",
    TURNSTILE_SECRET_KEY="turnstile-secret-test",
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
)
class SignupTurnstileTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.signup = {
            "restaurant_name": "Captcha Test Cafe",
            "email": "captcha-signup@example.test",
            "phone": "+49305550042",
            "password": "a-strong-test-password-42",
            "accept_terms": True,
            "b2b_confirmation": True,
            "cf-turnstile-response": "turnstile-response-test",
        }

    def test_register_page_has_only_turnstile_and_keeps_app_source(self):
        html = self.client.get("/auth/register/?source=app").content.decode()
        self.assertIn('class="cf-turnstile"', html)
        self.assertIn('data-callback="signupTurnstileVerified"', html)
        self.assertIn('data-expired-callback="signupTurnstileExpired"', html)
        self.assertIn('name="source" value="app"', html)
        self.assertIn('body["cf-turnstile-response"] = captchaToken', html)
        self.assertNotIn("grecaptcha", html)
        self.assertNotIn("g-recaptcha", html)
        self.assertNotIn("g-recaptcha-response", html)
        self.assertNotIn("signupRecaptchaVerified", html)
        self.assertIn('id="signup-error-phone"', html)
        self.assertIn('id="signup-error-email"', html)
        self.assertIn("let signupInFlight = false", html)
        self.assertIn("resetSignupCaptcha();", html)
        self.assertIn('name="accept_terms" required', html)
        self.assertIn('name="b2b_confirmation" required', html)

    def test_turnstile_messages_are_compiled_for_all_active_languages(self):
        languages = ("ar", "cs", "de", "el", "en", "es", "fr", "it", "ja", "ko", "nl", "pl", "pt", "ru", "tr", "zh_Hans")
        source = "Please complete the security check."
        for language in languages:
            with override(language):
                translated = gettext(source)
            self.assertTrue(translated, language)
            if language != "en":
                self.assertNotEqual(translated, source, language)

    def test_valid_turnstile_without_any_google_token_passes_captcha(self):
        with (
            patch("business_menu.views.verify_captcha_response", return_value=(True, "verified")) as verify,
            patch("business_menu.views._send_signup_verification_email", return_value=True),
        ):
            response = self.client.post("/api/business-menu/signup/", self.signup, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["email_verification_required"])
        verify.assert_called_once_with("turnstile", "turnstile-response-test", remoteip="127.0.0.1")

    def test_invalid_turnstile_response_is_rejected(self):
        with patch(
            "business_menu.views.verify_captcha_response",
            return_value=(False, "invalid_token"),
        ) as verify:
            response = self.client.post("/api/business-menu/signup/", self.signup, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "captcha_turnstile_invalid_token")
        self.assertEqual(response.json()["message"], "Please complete the security check.")
        verify.assert_called_once()

    def test_provider_configuration_error_is_not_reported_as_user_omission(self):
        with patch("business_menu.views.verify_captcha_response", return_value=(False, "configuration_error")):
            response = self.client.post("/api/business-menu/signup/", self.signup, format="json")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["code"], "captcha_turnstile_configuration_error")
        self.assertEqual(
            response.json()["message"],
            "Security verification is temporarily unavailable. Please try again later.",
        )

    def test_expired_token_requests_a_fresh_security_check(self):
        with patch("business_menu.views.verify_captcha_response", return_value=(False, "expired_or_duplicate")):
            response = self.client.post("/api/business-menu/signup/", self.signup, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["message"],
            "Security verification expired or was already used. Please complete it again.",
        )

    def test_field_error_is_distinct_and_retry_uses_a_fresh_turnstile_token(self):
        invalid_field_attempt = {**self.signup, "phone": "not-a-phone"}
        retry = {**self.signup, "email": "captcha-retry@example.test", "cf-turnstile-response": "fresh-turnstile-response-test"}
        with (
            patch("business_menu.views.verify_captcha_response", side_effect=[(True, "verified"), (True, "verified")]) as verify,
            patch("business_menu.views._send_signup_verification_email", return_value=True),
        ):
            first = self.client.post("/api/business-menu/signup/", invalid_field_attempt, format="json")
            second = self.client.post("/api/business-menu/signup/", retry, format="json")

        self.assertEqual(first.status_code, 400)
        self.assertIn("phone", first.json()["errors"])
        self.assertNotIn("code", first.json())
        self.assertEqual(second.status_code, 200)
        self.assertTrue(second.json()["email_verification_required"])
        self.assertEqual(
            [call.args[1] for call in verify.call_args_list],
            ["turnstile-response-test", "fresh-turnstile-response-test"],
        )


@override_settings(TURNSTILE_SECRET_KEY="turnstile-secret-test")
class TurnstileSiteverifyTests(SimpleTestCase):
    token = "turnstile-response-test"

    @staticmethod
    def response(status_code, payload=None, content_type="application/json"):
        response = requests.Response()
        response.status_code = status_code
        response.headers["Content-Type"] = content_type
        response._content = json.dumps(payload).encode() if payload is not None else b"not-json"
        return response

    def verify(self):
        from accounts.email_safety import verify_captcha_response

        return verify_captcha_response("turnstile", self.token, remoteip="127.0.0.1")

    @patch("accounts.email_safety.requests.post")
    def test_missing_token_does_not_call_provider(self, post):
        from accounts.email_safety import verify_captcha_response

        self.assertEqual(verify_captcha_response("turnstile", ""), (False, "missing_token"))
        post.assert_not_called()

    @patch("accounts.email_safety.requests.post")
    def test_success(self, post):
        post.return_value = self.response(200, {"success": True, "error-codes": []})

        self.assertEqual(self.verify(), (True, "verified"))
        self.assertEqual(post.call_args.kwargs["data"]["response"], self.token)
        self.assertEqual(post.call_args.kwargs["data"]["remoteip"], "127.0.0.1")
        self.assertEqual(post.call_args.kwargs["timeout"], (3.05, 5))
        self.assertFalse(post.call_args.kwargs["allow_redirects"])

    @patch("accounts.email_safety.requests.post")
    def test_invalid_token(self, post):
        post.return_value = self.response(200, {"success": False, "error-codes": ["invalid-input-response"]})

        self.assertEqual(self.verify(), (False, "invalid_token"))

    @patch("accounts.email_safety.requests.post")
    def test_expired_or_duplicate_token(self, post):
        post.return_value = self.response(200, {"success": False, "error-codes": ["timeout-or-duplicate"]})

        self.assertEqual(self.verify(), (False, "expired_or_duplicate"))

    @patch("accounts.email_safety.requests.post")
    def test_http_error_retries_once_with_same_idempotency_key(self, post):
        post.return_value = self.response(503, {"success": False, "error-codes": ["internal-error"]})

        self.assertEqual(self.verify(), (False, "provider_http_error"))
        self.assertEqual(post.call_count, 2)
        self.assertEqual(
            post.call_args_list[0].kwargs["data"]["idempotency_key"],
            post.call_args_list[1].kwargs["data"]["idempotency_key"],
        )

    @patch("accounts.email_safety.requests.post")
    def test_http_invalid_secret_is_configuration_error_and_logs_no_credentials(self, post):
        post.return_value = self.response(400, {"success": False, "error-codes": ["invalid-input-secret"]})

        with self.assertLogs("accounts.email_safety", level="WARNING") as logs:
            self.assertEqual(self.verify(), (False, "configuration_error"))

        output = " ".join(logs.output)
        self.assertIn("status=400", output)
        self.assertIn("invalid-input-secret", output)
        self.assertNotIn(self.token, output)
        self.assertNotIn("turnstile-secret-test", output)

    @patch("accounts.email_safety.requests.post")
    def test_non_json_response(self, post):
        post.return_value = self.response(200, content_type="text/html")

        self.assertEqual(self.verify(), (False, "provider_invalid_response"))

    @patch("accounts.email_safety.requests.post", side_effect=requests.Timeout)
    def test_timeout_retries_once_with_same_idempotency_key(self, post):
        self.assertEqual(self.verify(), (False, "provider_timeout"))
        self.assertEqual(post.call_count, 2)
        self.assertEqual(
            post.call_args_list[0].kwargs["data"]["idempotency_key"],
            post.call_args_list[1].kwargs["data"]["idempotency_key"],
        )
