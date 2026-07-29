"""Shared outbound-email abuse controls.

All counters use Django's cache backend so Redis deployments share limits across
Gunicorn workers and containers. The locmem backend still keeps tests/simple
development working.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import re
from dataclasses import dataclass

import requests
from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.mail import get_connection, send_mail
from django.core.validators import validate_email

logger = logging.getLogger(__name__)

EMAIL_GENERIC_RESPONSE = {"detail": "If the email can receive messages, a code will be sent."}


@dataclass(frozen=True)
class LimitRule:
    name: str
    key: str
    limit: int
    window_seconds: int


def setting_int(name: str, default: int) -> int:
    try:
        value = int(getattr(settings, name, default))
    except (TypeError, ValueError):
        return default
    return max(value, 0)


def normalize_email_address(email: str) -> str:
    return (email or "").strip().lower()


def validate_recipient_email(email: str) -> str:
    normalized = normalize_email_address(email)
    if len(normalized) > 254 or "\r" in normalized or "\n" in normalized:
        raise ValidationError("Invalid email address")
    validate_email(normalized)
    return normalized


def validate_header_value(value: str, max_length: int = 160) -> str:
    text = (value or "").strip()
    if len(text) > max_length or "\r" in text or "\n" in text:
        raise ValidationError("Invalid header value")
    return text


def validate_message_text(value: str, max_length: int = 5000) -> str:
    text = (value or "").strip()
    if len(text) > max_length:
        raise ValidationError("Message is too long")
    return text


def get_client_ip(request) -> str:
    xff = (request.META.get("HTTP_X_FORWARDED_FOR") or "").strip()
    if xff:
        return xff.split(",")[0].strip()[:45]
    return (request.META.get("REMOTE_ADDR") or "")[:45]


def fingerprint(value: str, prefix: str = "fp") -> str:
    secret = str(getattr(settings, "SECRET_KEY", "unsafe")).encode("utf-8")
    digest = hmac.new(secret, (value or "").encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{prefix}:{digest[:24]}"


def _cache_incr(key: str, window_seconds: int) -> int:
    added = cache.add(key, 1, timeout=window_seconds)
    if added:
        return 1
    try:
        return int(cache.incr(key))
    except ValueError:
        cache.set(key, 1, timeout=window_seconds)
        return 1


def check_rate_limits(action: str, rules: list[LimitRule], *, request=None, email: str = "") -> tuple[bool, str]:
    for rule in rules:
        if rule.limit <= 0:
            continue
        count = _cache_incr(rule.key, rule.window_seconds)
        if count > rule.limit:
            email_fp = fingerprint(normalize_email_address(email), "email") if email else ""
            ip_fp = fingerprint(get_client_ip(request), "ip") if request is not None else ""
            logger.warning(
                "email_rate_limit_blocked action=%s rule=%s limit=%s window=%s email_fp=%s ip_fp=%s",
                action,
                rule.name,
                rule.limit,
                rule.window_seconds,
                email_fp,
                ip_fp,
            )
            return False, rule.name
    return True, ""


def email_rules(action: str, email: str, request=None) -> list[LimitRule]:
    normalized = normalize_email_address(email)
    email_fp = fingerprint(normalized, "email")
    ip_fp = fingerprint(get_client_ip(request), "ip") if request is not None else "ip:none"

    if action in {"registration_verification", "email_verification"}:
        return [
            LimitRule("email_15m", f"emailsafe:{action}:{email_fp}:15m", setting_int("EMAIL_LIMIT_REGISTRATION_PER_EMAIL_15M", 3), 15 * 60),
            LimitRule("ip_1h", f"emailsafe:{action}:{ip_fp}:1h", setting_int("EMAIL_LIMIT_REGISTRATION_PER_IP_1H", 10), 60 * 60),
        ]
    if action in {"password_reset", "customer_password_reset", "business_password_reset"}:
        return [
            LimitRule("email_30m", f"emailsafe:{action}:{email_fp}:30m", setting_int("EMAIL_LIMIT_PASSWORD_RESET_PER_EMAIL_30M", 3), 30 * 60),
            LimitRule("ip_1h", f"emailsafe:{action}:{ip_fp}:1h", setting_int("EMAIL_LIMIT_PASSWORD_RESET_PER_IP_1H", 10), 60 * 60),
        ]
    if action == "contact_support":
        return [
            LimitRule("ip_10m", f"emailsafe:{action}:{ip_fp}:10m", setting_int("EMAIL_LIMIT_CONTACT_PER_IP_10M", 5), 10 * 60),
            LimitRule("email_1h", f"emailsafe:{action}:{email_fp}:1h", setting_int("EMAIL_LIMIT_CONTACT_PER_EMAIL_1H", 3), 60 * 60),
        ]
    return []


def check_email_action(action: str, email: str, *, request=None) -> tuple[bool, str]:
    return check_rate_limits(action, email_rules(action, email, request), request=request, email=email)


def acquire_email_cooldown(action: str, email: str, seconds: int | None = None) -> bool:
    seconds = setting_int("EMAIL_ACTION_COOLDOWN_SECONDS", 60) if seconds is None else max(int(seconds), 0)
    if seconds <= 0:
        return True
    key = f"emailsafe:cooldown:{action}:{fingerprint(normalize_email_address(email), 'email')}"
    return cache.add(key, 1, timeout=seconds)


def acquire_task_lock(action: str, identity: str, seconds: int | None = None) -> bool:
    seconds = setting_int("EMAIL_TASK_LOCK_SECONDS", 10 * 60) if seconds is None else max(int(seconds), 0)
    if seconds <= 0:
        return True
    key = f"emailsafe:task:{action}:{fingerprint(str(identity), 'task')}"
    return cache.add(key, 1, timeout=seconds)


def check_global_email_limit(action: str = "email") -> bool:
    limit = setting_int("EMAIL_GLOBAL_SAFETY_LIMIT", 200)
    window = setting_int("EMAIL_GLOBAL_SAFETY_WINDOW_SECONDS", 60 * 60)
    if limit <= 0:
        return True
    count = _cache_incr("emailsafe:global", window)
    if count > limit:
        logger.warning("global_outbound_email_safety_limit_reached action=%s limit=%s window=%s", action, limit, window)
        return False
    return True


def safe_send_mail(*, action: str, subject: str, message: str, from_email: str | None, recipient_list: list[str], **kwargs):
    if not check_global_email_limit(action):
        return 0
    safe_recipients = [validate_recipient_email(email) for email in recipient_list]
    safe_subject = validate_header_value(subject)
    from_addr = validate_recipient_email(from_email or getattr(settings, "DEFAULT_FROM_EMAIL", ""))
    return send_mail(
        subject=safe_subject,
        message=validate_message_text(message, max_length=20000),
        from_email=from_addr,
        recipient_list=safe_recipients,
        **kwargs,
    )


def get_configured_email_connection(timeout: int = 30):
    backend = getattr(settings, "EMAIL_BACKEND", "")
    if backend and backend != "django.core.mail.backends.smtp.EmailBackend":
        return get_connection(backend=backend)
    return get_connection(
        backend="django.core.mail.backends.smtp.EmailBackend",
        host=getattr(settings, "BONUS_EMAIL_HOST", getattr(settings, "EMAIL_HOST", "")),
        port=getattr(settings, "BONUS_EMAIL_PORT", getattr(settings, "EMAIL_PORT", 587)),
        username=getattr(settings, "BONUS_EMAIL_HOST_USER", getattr(settings, "EMAIL_HOST_USER", "")),
        password=getattr(settings, "BONUS_EMAIL_HOST_PASSWORD", getattr(settings, "EMAIL_HOST_PASSWORD", "")),
        use_tls=getattr(settings, "BONUS_EMAIL_USE_TLS", getattr(settings, "EMAIL_USE_TLS", True)),
        timeout=timeout,
    )


def is_honeypot_filled(data) -> bool:
    for name in ("website", "company_website", "homepage", "fax"):
        if (data.get(name) or "").strip():
            return True
    return False


def turnstile_required() -> bool:
    return bool((getattr(settings, "TURNSTILE_SECRET_KEY", "") or "").strip())


def verify_turnstile(token: str, *, remoteip: str = "") -> bool:
    secret = (getattr(settings, "TURNSTILE_SECRET_KEY", "") or "").strip()
    if not secret:
        return True
    token = (token or "").strip()
    if not token:
        return False
    try:
        response = requests.post(
            "https://challenges.cloudflare.com/turnstile/v0/siteverify",
            data={"secret": secret, "response": token, "remoteip": remoteip},
            timeout=8,
        )
        data = response.json() if response.ok else {}
        return data.get("success") is True
    except Exception:
        logger.warning("turnstile_validation_failed", exc_info=True)
        return False


def csrf_origin_allowed(request) -> bool:
    origin = request.META.get("HTTP_ORIGIN") or ""
    if not origin:
        return True
    allowed = [h.strip().rstrip("/") for h in getattr(settings, "CSRF_TRUSTED_ORIGINS", [])]
    allowed += [str(getattr(settings, "SITE_URL", "")).rstrip("/")]
    return origin.rstrip("/") in {a for a in allowed if a}
