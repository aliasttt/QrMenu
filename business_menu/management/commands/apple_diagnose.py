"""
Diagnose Apple App Store Server API JWT / connectivity.

Usage on Scalingo:
    scalingo --app qrmenu run "python manage.py apple_diagnose"
    scalingo --app qrmenu run "python manage.py apple_diagnose --transaction-id 2000001222795835 --environment Sandbox"
"""
from __future__ import annotations

import base64
import json

import requests
from django.core.management.base import BaseCommand

from business_menu.subscription_services import (
    _apple_base_url,
    _apple_server_jwt,
    _apple_settings,
    _normalise_apple_private_key,
)


def _b64url_decode(value: str) -> bytes:
    value = value + "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value.encode("ascii"))


class Command(BaseCommand):
    help = "Diagnose Apple App Store Server API JWT and connectivity."

    def add_arguments(self, parser):
        parser.add_argument("--transaction-id", default="", help="Optional transactionId to fetch (Sandbox or Production)")
        parser.add_argument("--environment", default="Sandbox", help="Sandbox or Production (default: Sandbox)")

    def handle(self, *args, **options):
        self.stdout.write("=== Apple config ===")
        try:
            cfg = _apple_settings()
        except Exception as exc:
            self.stderr.write(self.style.ERROR(f"Config error: {exc}"))
            return

        pk_raw = _normalise_apple_private_key(cfg["private_key"])
        pk_has_begin = "-----BEGIN" in pk_raw
        pk_lines = pk_raw.count("\n")

        self.stdout.write(f"  issuer_id      = {cfg['issuer_id']!r}  (len={len(cfg['issuer_id'])}, expected UUID length 36)")
        self.stdout.write(f"  key_id         = {cfg['key_id']!r}  (len={len(cfg['key_id'])}, expected 10)")
        self.stdout.write(f"  bundle_id      = {cfg['bundle_id']!r}")
        self.stdout.write(f"  private_key    = {len(pk_raw)} chars, {pk_lines} newlines, has BEGIN header: {pk_has_begin}")

        warnings = []
        if len(cfg["issuer_id"]) != 36 or cfg["issuer_id"].count("-") != 4:
            warnings.append("issuer_id does not look like a UUID (36 chars, 4 dashes)")
        if len(cfg["key_id"]) != 10:
            warnings.append(f"key_id length is {len(cfg['key_id'])}, Apple key IDs are 10 chars")
        if not pk_has_begin:
            warnings.append("private_key is missing BEGIN header — normalisation may not have wrapped it correctly")
        if pk_lines < 3:
            warnings.append(f"private_key has only {pk_lines} newlines — the PEM body may be on one line")
        for w in warnings:
            self.stdout.write(self.style.WARNING(f"  [warn] {w}"))

        self.stdout.write("\n=== Generate JWT ===")
        try:
            token = _apple_server_jwt()
        except Exception as exc:
            self.stderr.write(self.style.ERROR(f"JWT generation failed: {exc}"))
            return

        try:
            header_b64, payload_b64, sig_b64 = token.split(".", 2)
            header = json.loads(_b64url_decode(header_b64))
            payload = json.loads(_b64url_decode(payload_b64))
        except Exception as exc:
            self.stderr.write(self.style.ERROR(f"Cannot decode our own JWT: {exc}"))
            return

        self.stdout.write(f"  header  = {header}")
        self.stdout.write(f"  payload = {payload}")
        self.stdout.write(f"  token   = {token}")
        self.stdout.write("  (paste the token at https://jwt.io to inspect)")

        env = options["environment"]
        tx_id = options["transaction_id"].strip()
        if not tx_id:
            tx_id = "1"
            self.stdout.write("\n=== Test call (no transaction-id provided, using dummy '1') ===")
            self.stdout.write("  Expected: 404 if JWT is accepted, 401 if JWT is rejected.")
        else:
            self.stdout.write(f"\n=== Test call for transaction {tx_id} ===")

        url = f"{_apple_base_url(env)}/inApps/v1/transactions/{tx_id}"
        self.stdout.write(f"  URL: {url}")
        try:
            resp = requests.get(
                url,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                timeout=15,
            )
        except requests.RequestException as exc:
            self.stderr.write(self.style.ERROR(f"Request failed: {exc}"))
            return

        self.stdout.write(f"  status: {resp.status_code} {resp.reason}")
        self.stdout.write(f"  headers: {dict(resp.headers)}")
        self.stdout.write(f"  body ({len(resp.text)} chars): {resp.text[:2000]!r}")

        if resp.status_code == 401:
            self.stdout.write(self.style.ERROR(
                "\n401 with empty body = Apple's edge auth rejected the JWT.\n"
                "This is NOT a transaction problem. Most likely causes:\n"
                "  (a) Key is from the 'App Store Connect API' tab instead of 'In-App Purchase' tab\n"
                "  (b) issuer_id belongs to a different tab/team than the key_id\n"
                "  (c) private_key was mangled by the env var (missing newlines inside the PEM body)\n"
                "  (d) The key was revoked in App Store Connect"
            ))
        elif resp.status_code == 404:
            self.stdout.write(self.style.SUCCESS(
                "\n404 = JWT was accepted; Apple just does not have this transaction id. "
                "Auth pipeline is HEALTHY. If you passed a real transactionId and still get 404, "
                "check that --environment matches where the transaction was made."
            ))
        elif resp.status_code == 200:
            self.stdout.write(self.style.SUCCESS("\nAuth OK and transaction found."))
