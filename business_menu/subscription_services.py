from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone as dt_timezone
from typing import Any

import requests
from django.conf import settings
from django.utils import timezone

APPLE_PRODUCT_ID_TO_PLAN = {
    "de.preismenu.monthly": "monthly",
    "de.preismenu.yearly": "yearly",
}
VALID_APPLE_PRODUCT_IDS = set(APPLE_PRODUCT_ID_TO_PLAN)


class SubscriptionVerificationError(Exception):
    status_code = 400
    code = "subscription_verification_failed"


class SubscriptionConfigurationError(SubscriptionVerificationError):
    status_code = 503
    code = "subscription_verification_not_configured"


class SubscriptionRejectedError(SubscriptionVerificationError):
    status_code = 400
    code = "subscription_rejected"


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


def plan_from_product_id(product_id: str) -> str:
    return APPLE_PRODUCT_ID_TO_PLAN.get(product_id, product_id or "monthly")


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

    payload = verify_compact_jws_signature(signed_transaction_info)
    cfg = _apple_settings()
    if payload.get("bundleId") and payload.get("bundleId") != cfg["bundle_id"]:
        raise SubscriptionRejectedError(
            f"Apple transaction bundleId ({payload.get('bundleId')}) does not match this app ({cfg['bundle_id']})"
        )
    if str(payload.get("transactionId") or "") != str(transaction_id):
        raise SubscriptionRejectedError("Apple transactionId mismatch")

    product_id = payload.get("productId") or ""
    allowed_products = _allowed_apple_products()
    if expected_product_id and product_id != expected_product_id:
        raise SubscriptionRejectedError("Apple product_id mismatch")
    if allowed_products and product_id not in allowed_products:
        raise SubscriptionRejectedError("Apple product_id is not allowed")

    return AppleTransactionResult(
        payload=payload,
        signed_transaction_info=signed_transaction_info,
        environment=payload.get("environment") or resolved_environment,
    )


def apply_apple_transaction_to_admin(admin, result: AppleTransactionResult):
    payload = result.payload
    product_id = payload.get("productId") or ""
    admin.payment_status = "paid" if result.is_entitled else "unpaid"
    admin.subscription_ends_at = result.expires_at
    admin.subscription_provider = "apple"
    admin.subscription_product_id = product_id
    admin.subscription_environment = result.environment or ""
    admin.subscription_original_transaction_id = payload.get("originalTransactionId") or ""
    admin.subscription_transaction_id = payload.get("transactionId") or ""
    admin.save(
        update_fields=[
            "payment_status",
            "subscription_ends_at",
            "subscription_provider",
            "subscription_product_id",
            "subscription_environment",
            "subscription_original_transaction_id",
            "subscription_transaction_id",
        ]
    )
    return admin
