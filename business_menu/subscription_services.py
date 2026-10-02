from __future__ import annotations

import base64
import calendar
import hashlib
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone as dt_timezone
from typing import Any
from urllib.parse import quote

import requests
from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

APPLE_PRODUCT_ID_TO_PLAN = {
    "de.preismenu.monthly": "monthly",
    "de.preismenu.yearly": "yearly",
    "de.mybonusberlin.monthly": "monthly",
    "de.mybonusberlin.yearly": "yearly",
}
VALID_APPLE_PRODUCT_IDS = set(APPLE_PRODUCT_ID_TO_PLAN)


class SubscriptionVerificationError(Exception):
    status_code = 422
    code = "subscription_verification_failed"


class SubscriptionConfigurationError(SubscriptionVerificationError):
    status_code = 503
    code = "subscription_verification_not_configured"


class SubscriptionRejectedError(SubscriptionVerificationError):
    status_code = 422
    code = "subscription_rejected"


class SubscriptionTemporaryError(SubscriptionVerificationError):
    status_code = 503
    code = "subscription_provider_temporarily_unavailable"


class SubscriptionOwnershipError(SubscriptionRejectedError):
    code = "subscription_already_bound"


@dataclass
class AppleTransactionResult:
    payload: dict[str, Any]
    signed_transaction_info: str
    environment: str

    @property
    def expires_at(self):
        return _datetime_from_apple_ms(self.payload.get("expiresDate"))

    @property
    def is_entitled(self) -> bool:
        expires_at = self.expires_at
        if not expires_at or expires_at <= timezone.now():
            return False
        if self.payload.get("revocationDate"):
            return False
        return True


@dataclass
class GooglePlaySubscriptionResult:
    payload: dict[str, Any]
    purchase_token: str
    environment: str
    product_id: str
    base_plan_id: str
    status: str
    expires_at: datetime | None
    will_renew: bool | None
    latest_order_id: str
    linked_purchase_token: str
    acknowledgement_pending: bool


def _b64url_decode(value: str) -> bytes:
    value = value + "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value.encode("ascii"))


def decode_compact_jws_unverified(jws: str) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        header_b64, payload_b64, _signature_b64 = jws.split(".", 2)
        header = json.loads(_b64url_decode(header_b64))
        payload = json.loads(_b64url_decode(payload_b64))
    except Exception as exc:
        raise SubscriptionRejectedError("Invalid compact JWS") from exc
    if not isinstance(header, dict) or not isinstance(payload, dict):
        raise SubscriptionRejectedError("Invalid compact JWS payload")
    return header, payload


def _load_root_certificates():
    raw = getattr(settings, "APPLE_ROOT_CERTIFICATES_PEM", "") or ""
    if not raw.strip():
        return []
    from cryptography import x509

    pem = raw.replace("\\n", "\n").encode("utf-8")
    blocks = []
    marker = b"-----END CERTIFICATE-----"
    for part in pem.split(marker):
        part = part.strip()
        if part:
            blocks.append(part + b"\n" + marker + b"\n")
    return [x509.load_pem_x509_certificate(block) for block in blocks]


def _verify_certificate_signature(child, issuer):
    from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa

    public_key = issuer.public_key()
    if isinstance(public_key, rsa.RSAPublicKey):
        public_key.verify(child.signature, child.tbs_certificate_bytes, padding.PKCS1v15(), child.signature_hash_algorithm)
    elif isinstance(public_key, ec.EllipticCurvePublicKey):
        public_key.verify(child.signature, child.tbs_certificate_bytes, ec.ECDSA(child.signature_hash_algorithm))
    else:
        raise SubscriptionRejectedError("Unsupported Apple certificate key type")


def _verify_apple_certificate_chain(certs, require_trusted_root: bool):
    if not certs:
        raise SubscriptionRejectedError("Apple JWS certificate chain is empty")
    if require_trusted_root:
        now = datetime.now(dt_timezone.utc)
        for cert in certs:
            if cert.not_valid_before_utc > now or cert.not_valid_after_utc < now:
                raise SubscriptionRejectedError("Apple JWS certificate is not currently valid")
    if len(certs) > 1:
        for index in range(len(certs) - 1):
            _verify_certificate_signature(certs[index], certs[index + 1])

    roots = _load_root_certificates()
    if not roots:
        if require_trusted_root:
            raise SubscriptionConfigurationError("APPLE_ROOT_CERTIFICATES_PEM is required to trust Apple notifications")
        return

    issuer = certs[-1]
    for root in roots:
        try:
            _verify_certificate_signature(issuer, root)
            return
        except Exception:
            continue
    raise SubscriptionRejectedError("Apple JWS certificate chain is not anchored to a configured Apple root")


def verify_compact_jws_signature(jws: str, require_trusted_root: bool = False) -> dict[str, Any]:
    """Verify the ES256 JWS signature using Apple's x5c leaf cert when present."""
    try:
        from cryptography import x509
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric import ec, utils
        from cryptography.hazmat.primitives.hashes import SHA256
    except Exception as exc:
        raise SubscriptionConfigurationError("cryptography is required for Apple JWS verification") from exc

    try:
        header_b64, payload_b64, signature_b64 = jws.split(".", 2)
        header = json.loads(_b64url_decode(header_b64))
        payload = json.loads(_b64url_decode(payload_b64))
        signature = _b64url_decode(signature_b64)
        certs = header.get("x5c") or []
        if not certs:
            raise SubscriptionRejectedError("Apple JWS is missing x5c certificate chain")
        chain = [x509.load_der_x509_certificate(base64.b64decode(cert)) for cert in certs]
        _verify_apple_certificate_chain(chain, require_trusted_root=require_trusted_root)
        leaf_cert = chain[0]
        public_key = leaf_cert.public_key()
        if len(signature) != 64:
            raise SubscriptionRejectedError("Invalid ES256 signature length")
        r = int.from_bytes(signature[:32], "big")
        s = int.from_bytes(signature[32:], "big")
        der_signature = utils.encode_dss_signature(r, s)
        public_key.verify(
            der_signature,
            f"{header_b64}.{payload_b64}".encode("ascii"),
            ec.ECDSA(SHA256()),
        )
    except InvalidSignature as exc:
        raise SubscriptionRejectedError("Invalid Apple JWS signature") from exc
    except SubscriptionVerificationError:
        raise
    except Exception as exc:
        raise SubscriptionRejectedError("Could not verify Apple JWS") from exc
    return payload


def _datetime_from_apple_ms(value):
    if value in (None, ""):
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=dt_timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def _normalise_apple_private_key(value: str) -> str:
    key = (value or "").replace("\\n", "\n").strip()
    if not key:
        return ""
    if "-----BEGIN" not in key:
        body = "".join(key.split())
        wrapped = "\n".join(body[i : i + 64] for i in range(0, len(body), 64))
        key = f"-----BEGIN PRIVATE KEY-----\n{wrapped}\n-----END PRIVATE KEY-----\n"
    return key


def _normalise_apple_issuer_id(value: str) -> str:
    raw = (value or "").strip()
    if ":" in raw:
        raw = raw.split(":", 1)[1].strip()
    return raw


def _apple_settings() -> dict[str, str]:
    values = {
        "issuer_id": _normalise_apple_issuer_id(getattr(settings, "APPLE_APP_STORE_ISSUER_ID", "") or ""),
        "key_id": (getattr(settings, "APPLE_APP_STORE_KEY_ID", "") or "").strip(),
        "private_key": _normalise_apple_private_key(getattr(settings, "APPLE_APP_STORE_PRIVATE_KEY", "") or ""),
        "bundle_id": (getattr(settings, "APPLE_APP_BUNDLE_ID", "") or "").strip(),
    }
    missing = [key for key, value in values.items() if not value]
    if missing:
        raise SubscriptionConfigurationError(f"Missing Apple subscription settings: {', '.join(missing)}")
    return values


def _apple_server_jwt() -> str:
    try:
        import jwt
    except Exception as exc:
        raise SubscriptionConfigurationError("PyJWT is required for Apple server API JWTs") from exc

    cfg = _apple_settings()
    now = int(time.time())
    try:
        return jwt.encode(
            {
                "iss": cfg["issuer_id"],
                "iat": now,
                "exp": now + 20 * 60,
                "aud": "appstoreconnect-v1",
                "bid": cfg["bundle_id"],
            },
            cfg["private_key"],
            algorithm="ES256",
            headers={"kid": cfg["key_id"], "typ": "JWT"},
        )
    except SubscriptionVerificationError:
        raise
    except Exception as exc:
        raise SubscriptionConfigurationError(f"Apple server JWT could not be generated: {exc}") from exc


def _apple_base_url(environment: str) -> str:
    env = (environment or "").lower()
    if env == "sandbox":
        return (getattr(settings, "APPLE_APP_STORE_SANDBOX_URL", "") or "https://api.storekit-sandbox.itunes.apple.com").rstrip("/")
    return (getattr(settings, "APPLE_APP_STORE_PRODUCTION_URL", "") or "https://api.storekit.itunes.apple.com").rstrip("/")


def _allowed_apple_products() -> set[str]:
    raw = getattr(settings, "APPLE_SUBSCRIPTION_PRODUCT_IDS", "") or ""
    return VALID_APPLE_PRODUCT_IDS | {item.strip() for item in raw.split(",") if item.strip()}


def validate_apple_transaction_payload(payload, *, expected_transaction_id="", expected_product_id=""):
    cfg = _apple_settings()
    if payload.get("bundleId") and payload.get("bundleId") != cfg["bundle_id"]:
        raise SubscriptionRejectedError("Apple transaction bundleId does not match this app")
    if expected_transaction_id and str(payload.get("transactionId") or "") != str(expected_transaction_id):
        raise SubscriptionRejectedError("Apple transactionId mismatch")
    product_id = payload.get("productId") or ""
    if expected_product_id and product_id != expected_product_id:
        raise SubscriptionRejectedError("Apple product_id mismatch")
    allowed_products = _allowed_apple_products()
    if allowed_products and product_id not in allowed_products:
        raise SubscriptionRejectedError("Apple product_id is not allowed")


def plan_from_product_id(product_id: str) -> str:
    if not product_id:
        return "monthly"
    if product_id in APPLE_PRODUCT_ID_TO_PLAN:
        return APPLE_PRODUCT_ID_TO_PLAN[product_id]
    p_lower = str(product_id).lower()
    if "year" in p_lower or "annual" in p_lower:
        return "yearly"
    if "month" in p_lower:
        return "monthly"
    return product_id


def canonical_environment(provider: str, environment: str) -> str:
    provider = (provider or "").strip().lower()
    value = (environment or "").strip().lower()
    if provider == "apple":
        return "sandbox" if value == "sandbox" else "production" if value == "production" else value or "unknown"
    if provider == "stripe":
        if value in {"live", "production"}:
            return "live"
        if value in {"test", "sandbox"}:
            return "test"
        return value or "unknown"
    if provider == "google":
        return "test" if value in {"test", "sandbox"} else "production" if value == "production" else value or "unknown"
    if provider == "manual":
        return "manual"
    return value or "legacy"


def _environment_can_entitle(provider: str, environment: str) -> bool:
    environment = canonical_environment(provider, environment)
    if provider == "manual":
        return environment == "manual"
    production = {"apple": "production", "stripe": "live", "google": "production"}
    if environment == production.get(provider):
        return True
    return bool(getattr(settings, "ALLOW_TEST_SUBSCRIPTION_ENTITLEMENTS", False)) and environment in {"sandbox", "test"}


def _format_datetime(value):
    if not value:
        return None
    return value.isoformat().replace("+00:00", "Z") if hasattr(value, "isoformat") else str(value)


def add_calendar_months(value: datetime, months: int) -> datetime:
    """Add calendar months while keeping timezone/time and clamping month-end dates."""
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def resolve_subscription_entitlement(admin, *, now=None) -> dict[str, Any]:
    """Resolve one compatible entitlement without letting providers overwrite each other."""
    from .models import ProviderSubscription

    now = now or timezone.now()
    subscriptions = list(admin.provider_subscriptions.all())
    trusted = [
        item
        for item in subscriptions
        if item.verification_source
        in {ProviderSubscription.VerificationSource.PROVIDER, ProviderSubscription.VerificationSource.MANUAL}
    ]
    active_statuses = {
        ProviderSubscription.Status.ACTIVE,
        ProviderSubscription.Status.TRIALING,
        ProviderSubscription.Status.GRACE_PERIOD,
        ProviderSubscription.Status.CANCELED,
    }

    def is_active(item):
        return (
            item.status in active_statuses
            and item.current_period_end is not None
            and item.current_period_end > now
            and _environment_can_entitle(item.provider, item.environment)
        )

    active = [item for item in trusted if is_active(item)]
    chosen = max(active, key=lambda item: item.current_period_end) if active else None
    trial_end = getattr(admin, "trial_ends_at", None)
    internal_trial_active = bool(
        trial_end
        and trial_end > now
        and (getattr(admin, "payment_status", None) == "trial" or trusted)
    )
    access_blocked = bool(getattr(admin, "subscription_access_blocked", False))

    provider_rows = [
        {
            "provider": item.provider,
            "environment": item.environment,
            "product_id": item.product_id or None,
            "status": item.status,
            "current_period_end": _format_datetime(item.current_period_end),
            "will_renew": item.will_renew,
            "is_entitled": is_active(item) and not access_blocked,
            "needs_reconciliation": item.needs_reconciliation,
        }
        for item in subscriptions
    ]

    if access_blocked:
        return {
            "state": "blocked",
            "is_entitled": False,
            "plan": plan_from_product_id(chosen.product_id) if chosen else None,
            "provider": chosen.provider if chosen else None,
            "current_period_end": _format_datetime(chosen.current_period_end) if chosen else None,
            "will_renew": chosen.will_renew if chosen else False,
            "trial_end": _format_datetime(trial_end),
            "purchasable_in_app": False,
            "manage_url": None,
            "message": "Access is blocked by an administrator.",
            "providers": provider_rows,
            "entitlement_source": "admin_block",
            "trial_source": None,
            "app_account_token": str(admin.subscription_account_token),
            "decision_reason": "administratively_blocked",
            "access_blocked": True,
            "access_block_reason": admin.subscription_access_block_reason,
        }

    if chosen:
        return {
            "state": "active",
            "is_entitled": True,
            "plan": plan_from_product_id(chosen.product_id),
            "provider": chosen.provider,
            "current_period_end": _format_datetime(chosen.current_period_end),
            "will_renew": chosen.will_renew,
            "trial_end": _format_datetime(trial_end),
            "purchasable_in_app": False,
            "manage_url": None,
            "message": "",
            "providers": provider_rows,
            "entitlement_source": "manual" if chosen.provider == ProviderSubscription.Provider.MANUAL else "provider",
            "trial_source": "store" if chosen.status == ProviderSubscription.Status.TRIALING else None,
            "app_account_token": str(admin.subscription_account_token),
            "decision_reason": f"valid_{chosen.provider}_subscription",
            "access_blocked": False,
            "access_block_reason": "",
        }

    if internal_trial_active:
        return {
            "state": "trial",
            "is_entitled": True,
            "plan": "monthly",
            "provider": "manual",
            "current_period_end": _format_datetime(trial_end),
            "will_renew": False,
            "trial_end": _format_datetime(trial_end),
            "purchasable_in_app": False,
            "manage_url": None,
            "message": "",
            "providers": provider_rows,
            "entitlement_source": "internal_trial",
            "trial_source": "internal",
            "app_account_token": str(admin.subscription_account_token),
            "decision_reason": "valid_internal_trial",
            "access_blocked": False,
            "access_block_reason": "",
        }

    legacy_provider = (getattr(admin, "subscription_provider", "") or "").strip().lower()
    legacy_environment = canonical_environment(
        legacy_provider,
        getattr(admin, "subscription_environment", "") or "",
    )
    legacy_original_id = (getattr(admin, "subscription_original_transaction_id", "") or "").strip()

    def supersedes_legacy(item):
        if not legacy_provider or item.provider != legacy_provider:
            return False
        if legacy_environment not in {"", "unknown", "legacy"} and canonical_environment(
            item.provider, item.environment
        ) != legacy_environment:
            return False
        if legacy_original_id and item.provider == ProviderSubscription.Provider.APPLE:
            return item.external_id == legacy_original_id
        return True

    legacy_superseded = any(supersedes_legacy(item) for item in trusted)
    if not legacy_superseded and getattr(settings, "LEGACY_SUBSCRIPTION_FALLBACK_ENABLED", True):
        payment_status = getattr(admin, "payment_status", None)
        subscription_end = getattr(admin, "subscription_ends_at", None)
        if payment_status == "paid" and subscription_end and subscription_end > now:
            return {
                "state": "active",
                "is_entitled": True,
                "plan": plan_from_product_id(getattr(admin, "subscription_product_id", "")),
                "provider": getattr(admin, "subscription_provider", "") or "stripe",
                "current_period_end": _format_datetime(subscription_end),
                "will_renew": None,
                "trial_end": _format_datetime(trial_end),
                "purchasable_in_app": False,
                "manage_url": None,
                "message": "",
                "providers": provider_rows,
                "entitlement_source": "legacy",
                "trial_source": None,
                "app_account_token": str(admin.subscription_account_token),
                "decision_reason": "valid_legacy_subscription",
                "access_blocked": False,
                "access_block_reason": "",
            }

    latest_end = max((item.current_period_end for item in trusted if item.current_period_end), default=None)
    legacy_end = getattr(admin, "subscription_ends_at", None) or trial_end
    has_expired_context = bool(latest_end or legacy_end)
    return {
        "state": "expired" if has_expired_context else "none",
        "is_entitled": False,
        "plan": None,
        "provider": None,
        "current_period_end": _format_datetime(latest_end or legacy_end),
        "will_renew": False,
        "trial_end": _format_datetime(trial_end),
        "purchasable_in_app": True,
        "manage_url": None,
        "message": "",
        "providers": provider_rows,
        "entitlement_source": "provider" if trusted else "legacy",
        "trial_source": None,
        "app_account_token": str(admin.subscription_account_token),
        "decision_reason": "no_valid_subscription",
        "access_blocked": False,
        "access_block_reason": "",
    }


def apply_manual_subscription(
    account,
    *,
    event_id: str,
    plan: str,
    months: int | None = None,
    expires_at=None,
    extend: bool = False,
    now=None,
):
    """Create or update the one manual entitlement without fabricating provider payment data."""
    from .models import ProviderSubscription

    now = now or timezone.now()
    current = account.provider_subscriptions.filter(
        provider=ProviderSubscription.Provider.MANUAL,
        environment="manual",
        external_id=f"manual:{account.id}",
    ).first()
    if expires_at is None:
        base = max(now, current.current_period_end) if extend and current and current.current_period_end else now
        expires_at = add_calendar_months(base, months or 1)
    return apply_provider_event(
        account=account,
        provider=ProviderSubscription.Provider.MANUAL,
        environment="manual",
        external_id=f"manual:{account.id}",
        event_id=event_id,
        event_type="manual_extend" if extend else "manual_grant",
        status=ProviderSubscription.Status.ACTIVE,
        current_period_end=expires_at,
        occurred_at=now,
        product_id=plan,
        will_renew=False,
        verification_source=ProviderSubscription.VerificationSource.MANUAL,
    )


def cancel_manual_subscription(account, *, event_id: str, now=None):
    """Revoke only the manual entitlement; verified provider state is untouched."""
    from .models import ProviderSubscription

    now = now or timezone.now()
    current = account.provider_subscriptions.filter(
        provider=ProviderSubscription.Provider.MANUAL,
        environment="manual",
        external_id=f"manual:{account.id}",
    ).first()
    if not current:
        return None
    return apply_provider_event(
        account=account,
        provider=ProviderSubscription.Provider.MANUAL,
        environment="manual",
        external_id=current.external_id,
        event_id=event_id,
        event_type="manual_cancel",
        status=ProviderSubscription.Status.REVOKED,
        current_period_end=current.current_period_end,
        occurred_at=now,
        product_id=current.product_id,
        will_renew=False,
        verification_source=ProviderSubscription.VerificationSource.MANUAL,
    )


def _sync_legacy_subscription_fields(admin):
    """Keep the old app fields as a projection, never as competing provider state."""
    from .models import ProviderSubscription

    trusted_query = admin.provider_subscriptions.exclude(
        verification_source=ProviderSubscription.VerificationSource.LEGACY
    )
    trusted = list(trusted_query)
    if not trusted:
        return
    now = timezone.now()
    legacy_provider_name = (admin.subscription_provider or "").strip().lower()
    legacy_environment_name = canonical_environment(
        legacy_provider_name, admin.subscription_environment or ""
    )
    legacy_original_id = (admin.subscription_original_transaction_id or "").strip()
    legacy_still_valid = bool(
        admin.payment_status == "paid"
        and admin.subscription_ends_at
        and admin.subscription_ends_at > now
    )

    def supersedes_existing_legacy(item):
        if not legacy_provider_name or item.provider != legacy_provider_name:
            return False
        if legacy_environment_name not in {"", "unknown", "legacy"} and canonical_environment(
            item.provider, item.environment
        ) != legacy_environment_name:
            return False
        if legacy_original_id and item.provider == ProviderSubscription.Provider.APPLE:
            return item.external_id == legacy_original_id
        return True

    # Preserve independent legacy evidence until that provider purchase is reconciled.
    if legacy_still_valid and not any(supersedes_existing_legacy(item) for item in trusted):
        return
    active_statuses = {
        ProviderSubscription.Status.ACTIVE,
        ProviderSubscription.Status.TRIALING,
        ProviderSubscription.Status.GRACE_PERIOD,
        ProviderSubscription.Status.CANCELED,
    }
    eligible = [
        item
        for item in trusted
        if item.status in active_statuses
        and item.current_period_end
        and item.current_period_end > now
        and _environment_can_entitle(item.provider, item.environment)
    ]
    selected = max(eligible, key=lambda item: item.current_period_end) if eligible else None
    internal_trial_active = bool(
        admin.trial_ends_at
        and admin.trial_ends_at > now
        and (admin.payment_status == "trial" or trusted)
    )

    def legacy_environment(item):
        if item.provider == ProviderSubscription.Provider.APPLE:
            return "Sandbox" if item.environment == "sandbox" else "Production" if item.environment == "production" else item.environment
        if item.provider == ProviderSubscription.Provider.STRIPE:
            return "stripe"
        return item.environment

    if selected:
        admin.payment_status = "paid"
        admin.subscription_ends_at = selected.current_period_end
        admin.subscription_provider = selected.provider
        admin.subscription_product_id = selected.product_id
        admin.subscription_environment = legacy_environment(selected)
    elif internal_trial_active:
        admin.payment_status = "trial"
    elif not internal_trial_active:
        latest = trusted_query.order_by("-last_event_at", "-updated_at").first()
        admin.payment_status = "unpaid"
        if latest:
            admin.subscription_ends_at = latest.current_period_end
            admin.subscription_provider = latest.provider
            admin.subscription_product_id = latest.product_id
            admin.subscription_environment = legacy_environment(latest)
    admin.save(
        update_fields=[
            "payment_status",
            "subscription_ends_at",
            "subscription_provider",
            "subscription_product_id",
            "subscription_environment",
        ]
    )


def apply_provider_event(
    *,
    account,
    provider: str,
    environment: str,
    external_id: str,
    event_id: str,
    event_type: str,
    status: str,
    current_period_end,
    occurred_at=None,
    product_id: str = "",
    latest_transaction_id: str = "",
    provider_customer_id: str = "",
    will_renew=None,
    verification_source: str = "provider",
):
    """Atomically claim a provider purchase and apply one idempotent ordered event."""
    from .models import ProviderEvent, ProviderSubscription

    provider = (provider or "").strip().lower()
    environment = canonical_environment(provider, environment)
    external_id = str(external_id or "").strip()
    event_id = str(event_id or "").strip()
    latest_transaction_id = str(latest_transaction_id or "").strip()
    if not provider or not external_id or not event_id:
        raise SubscriptionRejectedError("Provider, external purchase ID, and event ID are required")

    with transaction.atomic():
        duplicate = ProviderEvent.objects.select_related("subscription").filter(
            provider=provider,
            environment=environment,
            external_event_id=event_id,
        ).first()
        if duplicate:
            if duplicate.subscription.account_id != account.id:
                raise SubscriptionOwnershipError("Provider event is already bound to another account")
            return duplicate.subscription, False, "duplicate"

        subscription = ProviderSubscription.objects.select_for_update().filter(
            provider=provider,
            environment=environment,
            external_id=external_id,
        ).first()
        if subscription and subscription.account_id != account.id:
            raise SubscriptionOwnershipError("Subscription purchase is already bound to another account")
        if subscription is None:
            try:
                with transaction.atomic():
                    subscription = ProviderSubscription.objects.create(
                        account=account,
                        provider=provider,
                        environment=environment,
                        external_id=external_id,
                    )
            except IntegrityError:
                subscription = ProviderSubscription.objects.select_for_update().get(
                    provider=provider,
                    environment=environment,
                    external_id=external_id,
                )
                if subscription.account_id != account.id:
                    raise SubscriptionOwnershipError("Subscription purchase is already bound to another account")

        if latest_transaction_id:
            conflicting = ProviderSubscription.objects.select_for_update().filter(
                provider=provider,
                environment=environment,
                latest_transaction_id=latest_transaction_id,
            ).exclude(pk=subscription.pk).first()
            if conflicting and conflicting.account_id != account.id:
                raise SubscriptionOwnershipError("Provider transaction is already bound to another account")

        state_applied = not (
            occurred_at and subscription.last_event_at and occurred_at < subscription.last_event_at
        )
        if state_applied:
            subscription.product_id = product_id or subscription.product_id
            subscription.status = status
            subscription.current_period_end = current_period_end
            subscription.will_renew = will_renew
            subscription.latest_transaction_id = latest_transaction_id or subscription.latest_transaction_id
            subscription.provider_customer_id = provider_customer_id or subscription.provider_customer_id
            subscription.verification_source = verification_source
            subscription.needs_reconciliation = False
            subscription.last_event_at = occurred_at or timezone.now()
            subscription.save()

        ProviderEvent.objects.create(
            subscription=subscription,
            provider=provider,
            environment=environment,
            external_event_id=event_id,
            event_type=event_type,
            occurred_at=occurred_at,
            state_applied=state_applied,
        )
        _sync_legacy_subscription_fields(account)
        return subscription, state_applied, "applied" if state_applied else "stale"


def google_purchase_external_id(purchase_token: str) -> str:
    """Stable non-secret identifier; the recoverable token is stored separately encrypted."""
    return hashlib.sha256(purchase_token.encode("utf-8")).hexdigest()


def _google_product_allowlist() -> dict[str, set[str]]:
    raw = getattr(settings, "GOOGLE_PLAY_SUBSCRIPTION_PRODUCTS_JSON", "") or ""
    try:
        data = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise SubscriptionConfigurationError("Google Play product mapping is not valid JSON") from exc
    if not isinstance(data, dict) or not data:
        raise SubscriptionConfigurationError("Google Play product mapping is required")
    result = {}
    for product_id, base_plans in data.items():
        if not isinstance(product_id, str) or not product_id.strip():
            raise SubscriptionConfigurationError("Google Play product mapping contains an invalid product")
        if isinstance(base_plans, str):
            base_plans = [base_plans]
        if not isinstance(base_plans, list) or not base_plans:
            raise SubscriptionConfigurationError("Every Google Play product needs allowed base plans")
        cleaned = {str(value).strip() for value in base_plans if str(value).strip()}
        if not cleaned:
            raise SubscriptionConfigurationError("Every Google Play product needs allowed base plans")
        result[product_id.strip()] = cleaned
    return result


def _google_token_cipher():
    key = (getattr(settings, "GOOGLE_PLAY_TOKEN_ENCRYPTION_KEY", "") or "").strip().encode("ascii")
    if not key:
        raise SubscriptionConfigurationError("Google Play token encryption key is required")
    try:
        from cryptography.fernet import Fernet

        return Fernet(key)
    except Exception as exc:
        raise SubscriptionConfigurationError("Google Play token encryption key is invalid") from exc


def encrypt_google_purchase_token(purchase_token: str) -> str:
    return _google_token_cipher().encrypt(purchase_token.encode("utf-8")).decode("ascii")


def decrypt_google_purchase_token(encrypted_token: str) -> str:
    try:
        return _google_token_cipher().decrypt(encrypted_token.encode("ascii")).decode("utf-8")
    except SubscriptionConfigurationError:
        raise
    except Exception as exc:
        raise SubscriptionConfigurationError("Stored Google Play token cannot be decrypted") from exc


def _google_authorized_session():
    try:
        import google.auth
        from google.auth.transport.requests import AuthorizedSession
        from google.oauth2 import service_account
    except ImportError as exc:
        raise SubscriptionConfigurationError("google-auth is required for Google Play verification") from exc

    scopes = ["https://www.googleapis.com/auth/androidpublisher"]
    encoded = (getattr(settings, "GOOGLE_PLAY_SERVICE_ACCOUNT_JSON_B64", "") or "").strip()
    try:
        if encoded:
            info = json.loads(base64.b64decode(encoded, validate=True))
            credentials = service_account.Credentials.from_service_account_info(info, scopes=scopes)
        else:
            credentials, _project = google.auth.default(scopes=scopes)
    except Exception as exc:
        raise SubscriptionConfigurationError("Google Play service credentials are unavailable") from exc
    return AuthorizedSession(credentials)


def _google_api_response(method: str, url: str, **kwargs):
    try:
        response = _google_authorized_session().request(method, url, timeout=15, **kwargs)
    except SubscriptionConfigurationError:
        raise
    except Exception as exc:
        raise SubscriptionTemporaryError("Google Play API request failed") from exc
    if response.status_code == 429 or response.status_code >= 500:
        raise SubscriptionTemporaryError("Google Play API is temporarily unavailable")
    if response.status_code >= 400:
        raise SubscriptionRejectedError("Google Play rejected the subscription request")
    return response


def _parse_google_timestamp(value) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise SubscriptionRejectedError("Google Play returned an invalid expiry time") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_timezone.utc)
    return parsed.astimezone(dt_timezone.utc)


def verify_google_play_subscription(purchase_token: str) -> GooglePlaySubscriptionResult:
    purchase_token = (purchase_token or "").strip()
    package_name = (getattr(settings, "GOOGLE_PLAY_PACKAGE_NAME", "") or "").strip()
    if not purchase_token:
        raise SubscriptionRejectedError("Google Play purchaseToken is required")
    if len(purchase_token) > 4096:
        raise SubscriptionRejectedError("Google Play purchaseToken is too long")
    if not package_name:
        raise SubscriptionConfigurationError("Google Play package name is required")
    allowlist = _google_product_allowlist()
    url = (
        "https://androidpublisher.googleapis.com/androidpublisher/v3/applications/"
        f"{quote(package_name, safe='')}/purchases/subscriptionsv2/tokens/{quote(purchase_token, safe='')}"
    )
    response = _google_api_response("GET", url)
    try:
        payload = response.json()
    except Exception as exc:
        raise SubscriptionTemporaryError("Google Play returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise SubscriptionTemporaryError("Google Play returned an invalid response")

    line_items = payload.get("lineItems") or []
    if not isinstance(line_items, list) or not line_items:
        raise SubscriptionRejectedError("Google Play subscription has no line items")
    validated_items = []
    for item in line_items:
        if not isinstance(item, dict):
            raise SubscriptionRejectedError("Google Play returned an invalid line item")
        product_id = str(item.get("productId") or "").strip()
        base_plan_id = str((item.get("offerDetails") or {}).get("basePlanId") or "").strip()
        if product_id not in allowlist or base_plan_id not in allowlist[product_id]:
            raise SubscriptionRejectedError("Google Play product or base plan is not allowed")
        validated_items.append((item, product_id, base_plan_id, _parse_google_timestamp(item.get("expiryTime"))))

    state = str(payload.get("subscriptionState") or "SUBSCRIPTION_STATE_UNSPECIFIED")
    status_map = {
        "SUBSCRIPTION_STATE_ACTIVE": "active",
        "SUBSCRIPTION_STATE_IN_GRACE_PERIOD": "grace_period",
        "SUBSCRIPTION_STATE_CANCELED": "canceled",
        "SUBSCRIPTION_STATE_EXPIRED": "expired",
        "SUBSCRIPTION_STATE_PAUSED": "unpaid",
        "SUBSCRIPTION_STATE_ON_HOLD": "unpaid",
        "SUBSCRIPTION_STATE_PENDING": "unknown",
        "SUBSCRIPTION_STATE_PENDING_PURCHASE_CANCELED": "expired",
    }
    subscription_status = status_map.get(state, "unknown")
    latest_item, product_id, base_plan_id, expires_at = max(
        validated_items,
        key=lambda row: row[3] or datetime.min.replace(tzinfo=dt_timezone.utc),
    )
    if subscription_status in {"active", "grace_period", "canceled"} and (
        expires_at is None or expires_at <= timezone.now()
    ):
        subscription_status = "expired"
    auto_renew_values = [
        item.get("autoRenewingPlan", {}).get("autoRenewEnabled")
        for item, _product, _plan, _expiry in validated_items
        if "autoRenewingPlan" in item
    ]
    will_renew = any(auto_renew_values) if auto_renew_values else None
    if state == "SUBSCRIPTION_STATE_CANCELED":
        will_renew = False
    environment = "test" if "testPurchase" in payload else "production"
    return GooglePlaySubscriptionResult(
        payload=payload,
        purchase_token=purchase_token,
        environment=environment,
        product_id=product_id,
        base_plan_id=base_plan_id,
        status=subscription_status,
        expires_at=expires_at,
        will_renew=will_renew,
        latest_order_id=str(latest_item.get("latestSuccessfulOrderId") or ""),
        linked_purchase_token=str(payload.get("linkedPurchaseToken") or ""),
        acknowledgement_pending=payload.get("acknowledgementState") == "ACKNOWLEDGEMENT_STATE_PENDING",
    )


def _google_owner_is_valid(account, result: GooglePlaySubscriptionResult) -> bool:
    from .models import ProviderSubscription

    external_id = google_purchase_external_id(result.purchase_token)
    existing_rows = list(ProviderSubscription.objects.filter(
        provider=ProviderSubscription.Provider.GOOGLE,
        external_id=external_id,
    )[:2])
    identifiers = result.payload.get("externalAccountIdentifiers") or {}
    claimed_ids = {
        str(identifiers.get("obfuscatedExternalAccountId") or "").strip().lower(),
        str(identifiers.get("externalAccountId") or "").strip().lower(),
    } - {""}
    expected = str(account.subscription_account_token).lower()
    if claimed_ids:
        if expected not in claimed_ids:
            raise SubscriptionOwnershipError("Google Play account identifier does not match this account")
        return True
    if existing_rows:
        if any(item.account_id != account.id for item in existing_rows):
            raise SubscriptionOwnershipError("Google Play purchase is already bound to another account")
        return True
    if result.linked_purchase_token:
        linked = ProviderSubscription.objects.filter(
            provider=ProviderSubscription.Provider.GOOGLE,
            external_id=google_purchase_external_id(result.linked_purchase_token),
        ).first()
        if linked:
            if linked.account_id != account.id:
                raise SubscriptionOwnershipError("Linked Google Play purchase belongs to another account")
            return True
    raise SubscriptionOwnershipError(
        "Google Play purchase has no matching account identifier or existing binding"
    )


def acknowledge_google_play_subscription(result: GooglePlaySubscriptionResult):
    if not result.acknowledgement_pending or result.status not in {"active", "grace_period", "canceled"}:
        return False
    package_name = (getattr(settings, "GOOGLE_PLAY_PACKAGE_NAME", "") or "").strip()
    url = (
        "https://androidpublisher.googleapis.com/androidpublisher/v3/applications/"
        f"{quote(package_name, safe='')}/purchases/subscriptions/{quote(result.product_id, safe='')}/"
        f"tokens/{quote(result.purchase_token, safe='')}:acknowledge"
    )
    _google_api_response("POST", url, json={})
    return True


def apply_google_play_subscription(
    account,
    result: GooglePlaySubscriptionResult,
    *,
    event_id: str = "",
    event_type: str = "purchase_verified",
    occurred_at=None,
):
    from .models import ProviderSubscription

    _google_owner_is_valid(account, result)
    external_id = google_purchase_external_id(result.purchase_token)
    event_id = event_id or f"verify:{external_id}:{result.payload.get('etag') or result.latest_order_id or result.status}"
    subscription, applied, outcome = apply_provider_event(
        account=account,
        provider=ProviderSubscription.Provider.GOOGLE,
        environment=result.environment,
        external_id=external_id,
        event_id=event_id,
        event_type=event_type,
        status=result.status,
        current_period_end=result.expires_at,
        occurred_at=occurred_at or timezone.now(),
        product_id=f"{result.product_id}:{result.base_plan_id}",
        latest_transaction_id=result.latest_order_id,
        provider_customer_id=encrypt_google_purchase_token(result.purchase_token),
        will_renew=result.will_renew,
    )
    if result.acknowledgement_pending and result.status in {"active", "grace_period", "canceled"}:
        try:
            acknowledge_google_play_subscription(result)
        except SubscriptionVerificationError:
            subscription.needs_reconciliation = True
            subscription.save(update_fields=["needs_reconciliation", "updated_at"])
            raise
        if subscription.needs_reconciliation:
            subscription.needs_reconciliation = False
            subscription.save(update_fields=["needs_reconciliation", "updated_at"])
    return subscription, applied, outcome


def verify_google_pubsub_token(authorization_header: str) -> dict[str, Any]:
    audience = (getattr(settings, "GOOGLE_PUBSUB_AUDIENCE", "") or "").strip()
    expected_email = (getattr(settings, "GOOGLE_PUBSUB_SERVICE_ACCOUNT_EMAIL", "") or "").strip().lower()
    if not audience or not expected_email:
        raise SubscriptionConfigurationError("Google Pub/Sub authentication is not configured")
    if not authorization_header.startswith("Bearer "):
        raise SubscriptionRejectedError("Google Pub/Sub bearer token is required")
    token = authorization_header[7:].strip()
    try:
        from google.auth.transport.requests import Request
        from google.oauth2 import id_token

        claims = id_token.verify_oauth2_token(token, Request(), audience=audience)
    except Exception as exc:
        raise SubscriptionRejectedError("Google Pub/Sub token is invalid") from exc
    if claims.get("iss") not in {"accounts.google.com", "https://accounts.google.com"}:
        raise SubscriptionRejectedError("Google Pub/Sub issuer is invalid")
    if str(claims.get("email") or "").lower() != expected_email or claims.get("email_verified") is not True:
        raise SubscriptionRejectedError("Google Pub/Sub service account is invalid")
    return claims


def verify_apple_transaction(jws: str, environment: str = "", expected_product_id: str = "") -> AppleTransactionResult:
    _header, device_payload = decode_compact_jws_unverified(jws)
    transaction_id = device_payload.get("transactionId") or device_payload.get("originalTransactionId")
    if not transaction_id:
        raise SubscriptionRejectedError("Apple transaction JWS is missing transactionId")

    resolved_environment = environment or device_payload.get("environment") or "Production"
    token = _apple_server_jwt()
    url = f"{_apple_base_url(resolved_environment)}/inApps/v1/transactions/{transaction_id}"
    try:
        response = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=15,
        )
    except requests.RequestException as exc:
        raise SubscriptionVerificationError("Apple verification request failed") from exc

    if response.status_code != 200:
        parts = []
        body_json = None
        try:
            body_json = response.json()
        except Exception:
            body_json = None
        if isinstance(body_json, dict):
            for key in ("errorMessage", "errorCode", "error", "message"):
                value = body_json.get(key)
                if value:
                    parts.append(f"{key}={value}")
        body_text = (response.text or "").strip()
        if not parts and body_text:
            parts.append(body_text[:400])
        reason = "; ".join(parts) or "no response body"
        hint = ""
        if response.status_code == 401:
            hint = (
                " (401 = Apple rejected our JWT. Verify APPLE_APP_STORE_KEY_ID / ISSUER_ID belong to an "
                "'In-App Purchase' key on the App Store Connect Users & Access → Integrations tab, "
                "APPLE_APP_BUNDLE_ID matches the bundle registered with that key, and "
                "APPLE_APP_STORE_PRIVATE_KEY still contains real newlines inside the PEM block.)"
            )
        raise SubscriptionRejectedError(
            f"Apple verification failed ({response.status_code} {response.reason or ''}): {reason}{hint}"
        )

    try:
        data = response.json()
    except Exception as exc:
        raise SubscriptionRejectedError("Apple response was not valid JSON") from exc
    signed_transaction_info = data.get("signedTransactionInfo")
    if not signed_transaction_info:
        raise SubscriptionRejectedError("Apple response missing signedTransactionInfo")

    payload = verify_compact_jws_signature(signed_transaction_info, require_trusted_root=True)
    validate_apple_transaction_payload(
        payload,
        expected_transaction_id=transaction_id,
        expected_product_id=expected_product_id,
    )

    return AppleTransactionResult(
        payload=payload,
        signed_transaction_info=signed_transaction_info,
        environment=payload.get("environment") or resolved_environment,
    )


def apply_apple_transaction_to_admin(admin, result: AppleTransactionResult):
    from .models import BusinessAdmin, ProviderSubscription

    payload = result.payload
    product_id = payload.get("productId") or ""
    original_transaction_id = str(payload.get("originalTransactionId") or "").strip()
    transaction_id = str(payload.get("transactionId") or "").strip()
    environment = canonical_environment("apple", result.environment or payload.get("environment") or "")
    if not original_transaction_id or not transaction_id:
        raise SubscriptionRejectedError("Apple transaction identifiers are required")

    app_account_token = str(payload.get("appAccountToken") or "").strip().lower()
    expected_account_token = str(admin.subscription_account_token).lower()
    if app_account_token:
        if app_account_token != expected_account_token:
            raise SubscriptionOwnershipError("Apple appAccountToken does not match this account")
    else:
        existing_owner = ProviderSubscription.objects.filter(
            provider=ProviderSubscription.Provider.APPLE,
            environment=environment,
            external_id=original_transaction_id,
        ).values_list("account_id", flat=True).first()
        legacy_owner_ids = list(
            BusinessAdmin.objects.filter(
                subscription_original_transaction_id=original_transaction_id,
            ).values_list("id", flat=True)[:2]
        )
        safely_bound = existing_owner == admin.id or legacy_owner_ids == [admin.id]
        if not safely_bound:
            raise SubscriptionOwnershipError(
                "Apple purchase has no appAccountToken or existing verified account binding"
            )

    if payload.get("revocationDate"):
        subscription_status = ProviderSubscription.Status.REVOKED
    elif result.is_entitled:
        subscription_status = ProviderSubscription.Status.ACTIVE
    else:
        subscription_status = ProviderSubscription.Status.EXPIRED
    signed_at = _datetime_from_apple_ms(payload.get("signedDate"))
    subscription, _applied, _reason = apply_provider_event(
        account=admin,
        provider=ProviderSubscription.Provider.APPLE,
        environment=environment,
        external_id=original_transaction_id,
        event_id=f"transaction:{transaction_id}",
        event_type="transaction_verified",
        status=subscription_status,
        current_period_end=result.expires_at,
        occurred_at=signed_at,
        product_id=product_id,
        latest_transaction_id=transaction_id,
        will_renew=None,
    )

    admin.subscription_original_transaction_id = original_transaction_id
    admin.subscription_transaction_id = transaction_id
    admin.save(
        update_fields=[
            "subscription_original_transaction_id",
            "subscription_transaction_id",
        ]
    )
    return subscription
