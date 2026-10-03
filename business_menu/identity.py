"""Canonical, domain-scoped identity validation for BusinessAdmin accounts."""

import phonenumbers
from django.core.exceptions import ValidationError
from django.core.validators import validate_email


def normalize_business_email(value):
    email = (value or "").strip().lower()
    if not email:
        raise ValidationError("Email is required.")
    validate_email(email)
    return email


def normalize_business_phone(value):
    raw = str(value or "").strip()
    if not raw:
        raise ValidationError("Phone number is required.")
    if raw.startswith("00"):
        raw = "+" + raw[2:]
    if not raw.startswith("+"):
        raise ValidationError("Enter an international phone number with its country code, for example +4930123456.")
    try:
        parsed = phonenumbers.parse(raw, None)
    except phonenumbers.NumberParseException as exc:
        raise ValidationError("Enter a valid international phone number with its country code.") from exc
    if parsed.extension or not phonenumbers.is_valid_number(parsed):
        raise ValidationError("Enter a valid international phone number with its country code.")
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
