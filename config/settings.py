"""
Merged: QR Menu Standalone (accounts + business_menu) + core frontend (our pages with style).
"""
from pathlib import Path
from datetime import timedelta
import os

from dotenv import load_dotenv
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", os.getenv("DJANGO_SECRET_KEY", "django-insecure-change-me"))


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name) or os.getenv(name)
    if raw is None:
        return default
    value = str(raw).strip().lower()
    if value in {"1", "true", "yes", "y", "on"}:
        return True
    if value in {"0", "false", "no", "n", "off"}:
        return False
    return default


# فعلاً True برای دیدن خطای 500 — بعد از رفع مشکل حتماً روی سرور DJANGO_DEBUG=0 بگذار
DEBUG = _env_bool("DJANGO_DEBUG", default=True)
_allowed = os.environ.get("ALLOWED_HOSTS") or os.getenv("DJANGO_ALLOWED_HOSTS")
_env_hosts = [h.strip() for h in _allowed.split(",") if h.strip()] if _allowed else []
_extra_hosts = [
    "localhost",
    "127.0.0.1",
    "qrmenu.osc-fr1.scalingo.io",
    "preismenu.de",
    "www.preismenu.de",
]
ALLOWED_HOSTS = list(dict.fromkeys(_extra_hosts + _env_hosts)) if _env_hosts else ["*"]

# OTP override for testing (optional)
_otp_override_raw = (os.environ.get("TEST_OTP_OVERRIDE_CODE") or os.getenv("TEST_OTP_OVERRIDE_CODE") or "").strip()
TEST_OTP_OVERRIDE_CODE = None if not _otp_override_raw or _otp_override_raw == "0" else _otp_override_raw
TEST_FORCE_REGISTRATION_AFTER_OTP = _env_bool("TEST_FORCE_REGISTRATION_AFTER_OTP", default=False)

# Core (our front pages) + accounts + business_menu
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework_simplejwt",
    "corsheaders",
    "django_filters",
    "drf_spectacular",
    "whitenoise.runserver_nostatic",
    "core",
    "accounts",
    "business_menu.apps.BusinessMenuConfig",
    "config",  # for management commands (e.g. migrate_from_source_db)
]

SIMPLE_JWT_ENABLE_BLACKLIST_APP = _env_bool("SIMPLE_JWT_ENABLE_BLACKLIST_APP", default=False)
if SIMPLE_JWT_ENABLE_BLACKLIST_APP:
    INSTALLED_APPS += ["rest_framework_simplejwt.token_blacklist"]

try:
    import cloudinary
    INSTALLED_APPS += ["cloudinary", "cloudinary_storage"]
except ImportError:
    pass

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "config.middleware.APIAppendSlashMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "accounts.middleware.UserActivityMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "config.middleware_security.SecurityHeadersMiddleware",
]

ROOT_URLCONF = "config.urls"

# Our templates first (core front with style), then bonusweb templates
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates", BASE_DIR / "templates_bonusweb"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.navigation_context",
                "core.context_processors.theme",
                "config.context_processors.firebase_settings",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

if os.environ.get("DATABASE_URL") or os.getenv("DATABASE_URL"):
    import dj_database_url
    _url = os.environ.get("DATABASE_URL") or os.getenv("DATABASE_URL")
    DATABASES = {"default": dj_database_url.parse(_url)}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en"
LANGUAGES = [("en", "English"), ("de", "Deutsch")]
LOCALE_PATHS = [BASE_DIR / "locale"]
TIME_ZONE = "Asia/Tehran"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATICFILES_DIRS = []
if (BASE_DIR / "static").exists():
    STATICFILES_DIRS.append(BASE_DIR / "static")
if (BASE_DIR / "static_bonusweb").exists():
    STATICFILES_DIRS.append(BASE_DIR / "static_bonusweb")
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

USE_CLOUDINARY = _env_bool("USE_CLOUDINARY", default=False)
CLOUDINARY_CLOUD_NAME = os.environ.get("CLOUDINARY_CLOUD_NAME", "") or os.getenv("CLOUDINARY_CLOUD_NAME", "")
CLOUDINARY_API_KEY = os.environ.get("CLOUDINARY_API_KEY", "") or os.getenv("CLOUDINARY_API_KEY", "")
CLOUDINARY_API_SECRET = os.environ.get("CLOUDINARY_API_SECRET", "") or os.getenv("CLOUDINARY_API_SECRET", "")

if USE_CLOUDINARY and CLOUDINARY_CLOUD_NAME and CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET:
    try:
        import cloudinary
        import cloudinary.uploader
        import cloudinary.api
        cloudinary.config(
            cloud_name=CLOUDINARY_CLOUD_NAME,
            api_key=CLOUDINARY_API_KEY,
            api_secret=CLOUDINARY_API_SECRET,
        )
        CLOUDINARY_STORAGE = {
            "CLOUD_NAME": CLOUDINARY_CLOUD_NAME,
            "API_KEY": CLOUDINARY_API_KEY,
            "API_SECRET": CLOUDINARY_API_SECRET,
            "SECURE": True,
        }
        STORAGES["default"] = {"BACKEND": "cloudinary_storage.storage.MediaCloudinaryStorage"}
        MEDIA_URL = "/media/"
    except ImportError:
        MEDIA_URL = "/media/"
        MEDIA_ROOT = BASE_DIR / "media"
else:
    MEDIA_URL = "/media/"
    MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "/admin/login/"
LOGIN_REDIRECT_URL = "/admin/"
SESSION_COOKIE_AGE = int(os.environ.get("SESSION_TIMEOUT_SECONDS", os.getenv("SESSION_TIMEOUT_SECONDS", "1800")))
SESSION_SAVE_EVERY_REQUEST = True
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"

CORS_ALLOW_ALL_ORIGINS = True

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.AllowAny",),
    "EXCEPTION_HANDLER": "config.drf_exception_handler.custom_exception_handler",
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_FILTER_BACKENDS": ("django_filters.rest_framework.DjangoFilterBackend",),
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(days=30),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=365),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": (
        SIMPLE_JWT_ENABLE_BLACKLIST_APP
        and _env_bool("SIMPLE_JWT_BLACKLIST_AFTER_ROTATION", default=False)
    ),
    "UPDATE_LAST_LOGIN": True,
    "CHECK_USER_IS_ACTIVE": True,
}

SPECTACULAR_SETTINGS = {
    "TITLE": "QR Menu API",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": True,
}

# Email
EMAIL_HOST = os.environ.get("EMAIL_HOST", os.getenv("EMAIL_HOST", "smtp.titan.email"))
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", os.getenv("EMAIL_PORT", "587")))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", os.getenv("EMAIL_HOST_USER", ""))
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", os.getenv("EMAIL_HOST_PASSWORD", ""))
EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", os.getenv("EMAIL_USE_TLS", "1")) == "1"
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", os.getenv("DEFAULT_FROM_EMAIL", "noreply@example.com"))
if EMAIL_HOST and EMAIL_HOST_USER and EMAIL_HOST_PASSWORD:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
else:
    EMAIL_BACKEND = os.environ.get("EMAIL_BACKEND", os.getenv("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend"))

# Twilio OTP
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "") or os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "") or os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_VERIFY_SERVICE_SID = os.environ.get("TWILIO_VERIFY_SERVICE_SID", "") or os.getenv("TWILIO_VERIFY_SERVICE_SID", "")
OTP_THROTTLE_RATE = os.environ.get("OTP_THROTTLE_RATE", os.getenv("OTP_THROTTLE_RATE", "5/minute"))

# Site base URL (for emails, Stripe redirects)
SITE_URL = os.environ.get("SITE_URL", "") or os.getenv("SITE_URL", "https://preismenu.de")

# reCAPTCHA (signup anti-bot) — from .env
RECAPTCHA_SITE_KEY = os.environ.get("RECAPTCHA_SITE_KEY", "") or os.getenv("RECAPTCHA_SITE_KEY", "")
RECAPTCHA_SECRET_KEY = os.environ.get("RECAPTCHA_SECRET_KEY", "") or os.getenv("RECAPTCHA_SECRET_KEY", "")

# Stripe (payments + Connect) — values only from .env / environment (never hardcode secrets here)
STRIPE_PUBLISHABLE_KEY = os.environ.get("STRIPE_PUBLISHABLE_KEY", "") or os.getenv("STRIPE_PUBLISHABLE_KEY", "")
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "") or os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "") or os.getenv("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PRICE_ID_ANNUAL = os.environ.get("STRIPE_PRICE_ID_ANNUAL", "") or os.getenv("STRIPE_PRICE_ID_ANNUAL", "")

# Firebase (optional)
FIREBASE_CONFIG = {}
VAPID_PUBLIC_KEY = os.environ.get("VAPID_PUBLIC_KEY", "") or os.getenv("VAPID_PUBLIC_KEY", "")

# App download (panel + public pages)
QR_MENU_APK_DEFAULT_URL = os.environ.get("APP_ANDROID_QR_MENU", os.getenv("APP_ANDROID_QR_MENU", "https://example.com/app.apk"))
MENU_PANEL_APK_DEFAULT_URL = QR_MENU_APK_DEFAULT_URL
APP_ANDROID_URL = os.environ.get("APP_ANDROID_URL", os.getenv("APP_ANDROID_URL", QR_MENU_APK_DEFAULT_URL))
APP_IOS_URL = os.environ.get("APP_IOS_URL", os.getenv("APP_IOS_URL", "https://apps.apple.com/app/id000000000"))

# Security (from config.security)
from config.security import get_security_settings
for key, value in get_security_settings().items():
    globals()[key] = value
