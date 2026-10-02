import base64
import json
import os
import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email

from business_menu.subscription_services import (
    SubscriptionConfigurationError,
    _google_authorized_session,
    _google_product_allowlist,
    _google_token_cipher,
)


RTDN_URL = "https://preismenu.de/api/business-menu/admin/subscriptions/google/notifications/"


class Command(BaseCommand):
    help = "Validate Google Play subscription configuration without printing secrets."

    def add_arguments(self, parser):
        parser.add_argument(
            "--check-credentials",
            action="store_true",
            help="Refresh an Android Publisher access token; performs a network call but no purchase action.",
        )

    def handle(self, *args, **options):
        errors = []
        package = settings.GOOGLE_PLAY_PACKAGE_NAME
        if (
            not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*)+", package or "")
            or ".example." in package
        ):
            errors.append("GOOGLE_PLAY_PACKAGE_NAME is missing or invalid")
        try:
            products = _google_product_allowlist()
            if any("YOUR_" in value for value in products) or any(
                "YOUR_" in plan for plans in products.values() for plan in plans
            ):
                raise SubscriptionConfigurationError("Google Play product mapping still contains placeholders")
            self.stdout.write(f"product_allowlist: valid ({len(products)} products)")
        except SubscriptionConfigurationError as exc:
            errors.append(str(exc))
        try:
            _google_token_cipher()
            self.stdout.write("token_encryption_key: valid")
        except SubscriptionConfigurationError as exc:
            errors.append(str(exc))

        encoded_credentials = settings.GOOGLE_PLAY_SERVICE_ACCOUNT_JSON_B64
        credential_source = "base64 service account" if encoded_credentials else (
            "ADC" if os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") else "missing"
        )
        if credential_source == "missing":
            errors.append("Google Play service credentials are missing")
        elif encoded_credentials:
            try:
                info = json.loads(base64.b64decode(encoded_credentials, validate=True))
                if info.get("type") != "service_account" or not all(
                    info.get(key) for key in ("client_email", "private_key")
                ):
                    raise ValueError
            except (ValueError, TypeError, json.JSONDecodeError):
                errors.append("GOOGLE_PLAY_SERVICE_ACCOUNT_JSON_B64 is not a valid service-account JSON")
        self.stdout.write(f"credential_source: {credential_source}")

        audience = settings.GOOGLE_PUBSUB_AUDIENCE
        if audience != RTDN_URL:
            errors.append(f"GOOGLE_PUBSUB_AUDIENCE must equal {RTDN_URL}")
        email = settings.GOOGLE_PUBSUB_SERVICE_ACCOUNT_EMAIL
        try:
            validate_email(email)
        except ValidationError:
            errors.append("GOOGLE_PUBSUB_SERVICE_ACCOUNT_EMAIL is missing or invalid")

        if options["check_credentials"] and credential_source != "missing":
            try:
                from google.auth.transport.requests import Request

                session = _google_authorized_session()
                session.credentials.refresh(Request())
                self.stdout.write("credential_authentication: success (no purchase checked)")
            except Exception:
                errors.append("credential_authentication failed")

        self.stdout.write(f"rtdn_url: {RTDN_URL}")
        self.stdout.write("purchase_verification: not tested")
        self.stdout.write("rtdn_delivery: not tested")
        self.stdout.write("acknowledgement: not tested")
        if errors:
            raise CommandError("; ".join(errors))
        self.stdout.write(self.style.SUCCESS("Google Play configuration is structurally ready."))
