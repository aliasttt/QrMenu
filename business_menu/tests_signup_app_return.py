from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from .models import BusinessAdmin, PendingEmailVerification


@override_settings(
    SECURE_SSL_REDIRECT=False,
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
)
class SignupAppReturnTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.signup_data = {
            "restaurant_name": "Return Test Cafe",
            "email": "plus+signup@example.com",
            "phone": "+49305550041",
            "password": "a-strong-test-password-41",
            "accept_terms": True,
            "b2b_confirmation": True,
        }

    def begin_signup(self, source=None):
        data = dict(self.signup_data)
        if source:
            data["source"] = source
        if source == "app":
            data["return_url"] = "https://evil.example/"
        with patch("business_menu.views._send_signup_verification_email", return_value=True):
            response = self.client.post("/api/business-menu/signup/", data, format="json")
        return response, PendingEmailVerification.objects.get(email__iexact=self.signup_data["email"])

    def complete_signup(self, pending):
        return self.client.post(
            "/api/business-menu/signup/",
            {"email": pending.email, "email_verification_code": pending.code},
            format="json",
        )

    def test_app_return_is_only_after_verified_account_commit_and_encodes_email(self):
        started, pending = self.begin_signup("app")
        self.assertEqual(started.status_code, 200)
        self.assertTrue(started.json()["email_verification_required"])
        self.assertNotIn("app_return_url", started.json())
        self.assertTrue(pending.signup_data["return_to_app"])

        invalid = self.client.post(
            "/api/business-menu/signup/",
            {"email": pending.email, "email_verification_code": "000000" if pending.code != "000000" else "111111"},
            format="json",
        )
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(User.objects.count(), 0)
        self.assertNotIn("app_return_url", invalid.json())

        completed = self.complete_signup(pending)
        self.assertEqual(completed.status_code, 201)
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(BusinessAdmin.objects.count(), 1)
        self.assertEqual(completed.json()["email"], "plus+signup@example.com")
        self.assertNotIn("panel_url", completed.json())
        callback = urlsplit(completed.json()["app_return_url"])
        self.assertEqual((callback.scheme, callback.netloc, callback.path), ("myqrmenu", "register-complete", ""))
        self.assertEqual(parse_qs(callback.query), {"email": ["plus+signup@example.com"]})
        self.assertIn("email=plus%2Bsignup%40example.com", completed.json()["app_return_url"])
        self.assertNotIn("password", completed.json()["app_return_url"].lower())
        self.assertNotIn("token", completed.json()["app_return_url"].lower())
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_web_signup_keeps_login_and_does_not_return_to_app(self):
        _, pending = self.begin_signup()
        completed = self.complete_signup(pending)

        self.assertEqual(completed.status_code, 201)
        self.assertIn("panel_url", completed.json())
        self.assertNotIn("app_return_url", completed.json())
        self.assertIn("_auth_user_id", self.client.session)

    def test_source_survives_registration_page_and_language_switch_target(self):
        response = self.client.get("/auth/register/?source=app")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('name="source" value="app"', content)
        self.assertIn('/de/auth/register/?source=app', content)
        self.assertIn('id="step-success" class="hidden"', content)

    def test_ordinary_registration_page_does_not_carry_app_source(self):
        response = self.client.get("/auth/register/")
        content = response.content.decode()
        self.assertNotIn('name="source" value="app"', content)
        self.assertNotIn("register-complete", content)

    def test_app_success_copy_renders_in_all_sixteen_site_languages(self):
        expected = {
            "en": (
                "Account created",
                "Your account is ready. Return to the app and sign in.",
                "Return to app and sign in",
                "If the app does not open, tap the return button or open the app and sign in.",
            ),
            "de": (
                "Konto erstellt",
                "Ihr Konto ist bereit. Kehren Sie zur App zur\u00fcck und melden Sie sich an.",
                "Zur\u00fcck zur App und anmelden",
                "Wenn sich die App nicht \u00f6ffnet, tippen Sie auf die Schaltfl\u00e4che unten oder \u00f6ffnen Sie die App und melden Sie sich an.",
            ),
            "tr": (
                "Hesap olu\u015fturuldu",
                "Hesab\u0131n\u0131z haz\u0131r. Uygulamaya d\u00f6n\u00fcp giri\u015f yap\u0131n.",
                "Uygulamaya d\u00f6n ve giri\u015f yap",
                "Uygulama a\u00e7\u0131lmazsa geri d\u00f6n d\u00fc\u011fmesine dokunun veya uygulamay\u0131 a\u00e7\u0131p giri\u015f yap\u0131n.",
            ),
            "ar": (
                "\u062a\u0645 \u0625\u0646\u0634\u0627\u0621 \u0627\u0644\u062d\u0633\u0627\u0628",
                "\u062d\u0633\u0627\u0628\u0643 \u062c\u0627\u0647\u0632. \u0639\u064f\u062f \u0625\u0644\u0649 \u0627\u0644\u062a\u0637\u0628\u064a\u0642 \u0648\u0633\u062c\u0651\u0644 \u0627\u0644\u062f\u062e\u0648\u0644.",
                "\u0627\u0644\u0639\u0648\u062f\u0629 \u0625\u0644\u0649 \u0627\u0644\u062a\u0637\u0628\u064a\u0642 \u0648\u062a\u0633\u062c\u064a\u0644 \u0627\u0644\u062f\u062e\u0648\u0644",
                "\u0625\u0630\u0627 \u0644\u0645 \u064a\u0641\u062a\u062d \u0627\u0644\u062a\u0637\u0628\u064a\u0642\u060c \u0641\u0627\u0636\u063a\u0637 \u0639\u0644\u0649 \u0632\u0631 \u0627\u0644\u0631\u062c\u0648\u0639 \u0623\u0648 \u0627\u0641\u062a\u062d \u0627\u0644\u062a\u0637\u0628\u064a\u0642 \u0648\u0633\u062c\u0651\u0644 \u0627\u0644\u062f\u062e\u0648\u0644.",
            ),
            "es": ("Cuenta creada", "Tu cuenta está lista. Vuelve a la aplicación e inicia sesión.", "Volver a la aplicación e iniciar sesión", "Si la aplicación no se abre, pulsa el botón para volver o abre la aplicación e inicia sesión."),
            "it": ("Account creato", "Il tuo account è pronto. Torna all'app e accedi.", "Torna all'app e accedi", "Se l'app non si apre, tocca il pulsante per tornare oppure apri l'app e accedi."),
            "fr": ("Compte créé", "Votre compte est prêt. Revenez à l’application et connectez-vous.", "Revenir à l’application et se connecter", "Si l’application ne s’ouvre pas, appuyez sur le bouton de retour ou ouvrez l’application et connectez-vous."),
            "ru": ("Аккаунт создан", "Ваш аккаунт готов. Вернитесь в приложение и войдите.", "Вернуться в приложение и войти", "Если приложение не открылось, нажмите кнопку возврата или откройте приложение и войдите."),
            "nl": ("Account aangemaakt", "Je account is klaar. Ga terug naar de app en log in.", "Terug naar de app en inloggen", "Als de app niet opent, tik je op de terugknop of open je de app en log je in."),
            "ja": ("アカウントを作成しました", "アカウントの準備ができました。アプリに戻ってログインしてください。", "アプリに戻ってログイン", "アプリが開かない場合は、戻るボタンをタップするか、アプリを開いてログインしてください。"),
            "el": ("Ο λογαριασμός δημιουργήθηκε", "Ο λογαριασμός σας είναι έτοιμος. Επιστρέψτε στην εφαρμογή και συνδεθείτε.", "Επιστροφή στην εφαρμογή και σύνδεση", "Αν η εφαρμογή δεν ανοίξει, πατήστε το κουμπί επιστροφής ή ανοίξτε την εφαρμογή και συνδεθείτε."),
            "cs": ("Účet byl vytvořen", "Váš účet je připraven. Vraťte se do aplikace a přihlaste se.", "Zpět do aplikace a přihlásit se", "Pokud se aplikace neotevře, klepněte na tlačítko návratu nebo aplikaci otevřete a přihlaste se."),
            "zh-hans": ("账户已创建", "您的账户已准备就绪。请返回应用并登录。", "返回应用并登录", "如果应用没有打开，请点击返回按钮，或打开应用并登录。"),
            "pt": ("Conta criada", "Sua conta está pronta. Volte ao aplicativo e entre.", "Voltar ao aplicativo e entrar", "Se o aplicativo não abrir, toque no botão de retorno ou abra o aplicativo e entre."),
            "ko": ("계정이 생성되었습니다", "계정이 준비되었습니다. 앱으로 돌아가 로그인하세요.", "앱으로 돌아가 로그인", "앱이 열리지 않으면 돌아가기 버튼을 누르거나 앱을 열어 로그인하세요."),
            "pl": ("Konto zostało utworzone", "Twoje konto jest gotowe. Wróć do aplikacji i zaloguj się.", "Wróć do aplikacji i zaloguj się", "Jeśli aplikacja się nie otworzy, naciśnij przycisk powrotu lub otwórz aplikację i zaloguj się."),
        }
        for language, translated_copy in expected.items():
            with self.subTest(language=language):
                self.client.cookies["django_language"] = language
                path = "/auth/register/" if language == "en" else f"/{language}/auth/register/"
                response = self.client.get(path + "?source=app", secure=True)
                content = response.content.decode()
                self.assertEqual(response.status_code, 200, language)
                for phrase in translated_copy:
                    self.assertTrue(phrase in content, language)
                self.assertTrue('id="app-return-link"' in content, language)
                self.assertTrue("max-w-md" in content and "mt-6 block w-full text-center" in content, language)
