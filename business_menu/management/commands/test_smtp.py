"""
Debug helper for SMTP configuration.

Usage on Scalingo:
    scalingo -a preismenu run python manage.py test_smtp --to your@email.com

It prints the effective SMTP config (username, host, port, password length +
first/last char only, TLS flag) and then attempts:
  1. A raw smtplib SMTP+STARTTLS connect + AUTH LOGIN
  2. A raw smtplib SMTP_SSL connect + AUTH LOGIN (fallback to port 465)
  3. A Django send_mail via the invoice email path

For each step it reports the actual server response so you can distinguish
between wrong credentials, wrong host/port, TLS mismatch, or a locked
mailbox.
"""
import smtplib
import ssl

from django.conf import settings
from django.core.management.base import BaseCommand


def _mask(pw: str) -> str:
    if not pw:
        return "<empty>"
    if len(pw) <= 4:
        return f"<{len(pw)} chars: too short to mask>"
    return f"{pw[0]}***{pw[-1]} (len={len(pw)})"


class Command(BaseCommand):
    help = "Diagnose SMTP configuration by attempting to send a test email."

    def add_arguments(self, parser):
        parser.add_argument("--to", required=True, help="Recipient email address")

    def handle(self, *args, **opts):
        to_addr = opts["to"]

        host = getattr(settings, "BONUS_EMAIL_HOST", settings.EMAIL_HOST)
        port = int(getattr(settings, "BONUS_EMAIL_PORT", getattr(settings, "EMAIL_PORT", 587)) or 587)
        user = getattr(settings, "BONUS_EMAIL_HOST_USER", getattr(settings, "EMAIL_HOST_USER", "")) or ""
        password = getattr(settings, "BONUS_EMAIL_HOST_PASSWORD", getattr(settings, "EMAIL_HOST_PASSWORD", "")) or ""
        use_tls = getattr(settings, "BONUS_EMAIL_USE_TLS", getattr(settings, "EMAIL_USE_TLS", True))

        try:
            from business_menu.invoice_email import _resolve_from_email
            from_email = _resolve_from_email()
        except Exception as e:
            from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "<none>")
            self.stdout.write(f"(_resolve_from_email failed: {e})")

        self.stdout.write(self.style.NOTICE("=== Effective SMTP config ==="))
        self.stdout.write(f"host              : {host}")
        self.stdout.write(f"port              : {port}")
        self.stdout.write(f"username          : {user!r}")
        self.stdout.write(f"password          : {_mask(password)}")
        self.stdout.write(f"use_tls           : {use_tls}")
        self.stdout.write(f"resolved FROM     : {from_email!r}")
        self.stdout.write(f"target recipient  : {to_addr!r}")
        self.stdout.write("")

        if not host or not user or not password:
            self.stdout.write(self.style.ERROR(
                "Missing host/user/password. Set EMAIL_HOST, EMAIL_HOST_USER, "
                "EMAIL_HOST_PASSWORD env vars on Scalingo, then restart the app."
            ))
            return

        self.stdout.write(self.style.NOTICE(f"=== Step 1: SMTP+STARTTLS on {host}:{port} ==="))
        self._try_starttls(host, port, user, password)
        self.stdout.write("")

        self.stdout.write(self.style.NOTICE(f"=== Step 2: SMTP_SSL on {host}:465 ==="))
        self._try_ssl(host, 465, user, password)
        self.stdout.write("")

        self.stdout.write(self.style.NOTICE("=== Step 3: Django send_mail ==="))
        try:
            from django.core.mail import EmailMessage, get_connection
            conn = get_connection(
                backend="django.core.mail.backends.smtp.EmailBackend",
                host=host, port=port, username=user, password=password,
                use_tls=use_tls, timeout=30,
            )
            msg = EmailMessage(
                subject="QRMenu SMTP diagnostic",
                body="If you see this, Django's SMTP path is working.",
                from_email=from_email,
                to=[to_addr],
                connection=conn,
            )
            sent = msg.send(fail_silently=False)
            self.stdout.write(self.style.SUCCESS(f"Django send() returned {sent} — check inbox / spam of {to_addr}"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Django send failed: {type(e).__name__}: {e}"))

    def _try_starttls(self, host, port, user, password):
        try:
            s = smtplib.SMTP(host, port, timeout=30)
            s.ehlo()
            s.starttls(context=ssl.create_default_context())
            s.ehlo()
            self.stdout.write(f"  AUTH mechanisms offered: {s.esmtp_features.get('auth', '<none>')}")
            code, resp = s.login(user, password)
            self.stdout.write(self.style.SUCCESS(f"  LOGIN OK ({code}): {resp!r}"))
            s.quit()
        except smtplib.SMTPAuthenticationError as e:
            self.stdout.write(self.style.ERROR(
                f"  535 auth rejected. Server said: {e.smtp_error!r}. "
                f"Meaning: username/password is not accepted. "
                f"→ Double-check the exact password in Titan webmail, or generate an SMTP-only app password."
            ))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"  STARTTLS failed: {type(e).__name__}: {e}"))

    def _try_ssl(self, host, port, user, password):
        try:
            s = smtplib.SMTP_SSL(host, port, timeout=30, context=ssl.create_default_context())
            s.ehlo()
            code, resp = s.login(user, password)
            self.stdout.write(self.style.SUCCESS(f"  LOGIN OK ({code}): {resp!r}"))
            s.quit()
        except smtplib.SMTPAuthenticationError as e:
            self.stdout.write(self.style.ERROR(
                f"  535 auth rejected on port 465 too — same credential problem."
            ))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"  SMTP_SSL failed: {type(e).__name__}: {e}"))
