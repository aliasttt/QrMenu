"""
Session-based auth for menu customers (end-users ordering food).
Completely separate from BusinessAdmin/JWT auth — do not mix.
"""
from __future__ import annotations

import re
from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny

from accounts.models import MenuCustomer, MenuCustomerAddress
from accounts.twilio_utils import format_phone_number

SESSION_KEY = "menu_customer_id"


def _normalize_phone(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        return ""
    try:
        return format_phone_number(raw) or raw
    except Exception:
        return raw


def _valid_email(email: str) -> bool:
    return bool(re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", email or ""))


def _get_logged_in_customer(request):
    cid = request.session.get(SESSION_KEY)
    if not cid:
        return None
    try:
        return MenuCustomer.objects.get(pk=cid, is_active=True)
    except MenuCustomer.DoesNotExist:
        return None


def _serialize_address(a: MenuCustomerAddress) -> dict:
    return {
        "id": a.id,
        "label": a.label,
        "address": a.address,
        "is_default": a.is_default,
    }


def _serialize_customer(c: MenuCustomer) -> dict:
    return {
        "id": c.id,
        "email": c.email,
        "phone": c.phone,
        "first_name": c.first_name,
        "last_name": c.last_name,
        "name": c.name,
        "addresses": [_serialize_address(a) for a in c.addresses.all()],
    }


class CustomerCheckPhoneView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        phone = _normalize_phone(request.data.get("phone"))
        if not phone:
            return Response({"detail": "phone_required"}, status=400)
        exists = MenuCustomer.objects.filter(phone=phone, is_active=True).exists()
        return Response({"exists": exists, "phone": phone})


class CustomerCheckEmailView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        email = (request.data.get("email") or "").strip().lower()
        if not _valid_email(email):
            return Response({"detail": "invalid_email"}, status=400)
        exists = MenuCustomer.objects.filter(email__iexact=email, is_active=True).exists()
        return Response({"exists": exists, "email": email})


class CustomerRegisterView(APIView):
    permission_classes = [AllowAny]

    @transaction.atomic
    def post(self, request):
        email = (request.data.get("email") or "").strip().lower()
        phone = _normalize_phone(request.data.get("phone"))
        password = (request.data.get("password") or "").strip()
        first_name = (request.data.get("first_name") or "").strip()
        last_name = (request.data.get("last_name") or "").strip()
        address = (request.data.get("address") or "").strip()

        if not _valid_email(email):
            return Response({"detail": "invalid_email"}, status=400)
        if not phone:
            return Response({"detail": "phone_required"}, status=400)
        if len(password) < 6:
            return Response({"detail": "password_min_6"}, status=400)
        if not first_name:
            return Response({"detail": "first_name_required"}, status=400)

        if MenuCustomer.objects.filter(email__iexact=email).exists():
            return Response({"detail": "email_already_registered"}, status=409)
        if MenuCustomer.objects.filter(phone=phone).exists():
            return Response({"detail": "phone_already_registered"}, status=409)

        try:
            customer = MenuCustomer(
                email=email,
                phone=phone,
                first_name=first_name,
                last_name=last_name,
            )
            customer.set_password(password)
            customer.save()

            if address:
                MenuCustomerAddress.objects.create(
                    customer=customer,
                    address=address,
                    is_default=True,
                )

            request.session[SESSION_KEY] = customer.id
            request.session.set_expiry(60 * 60 * 24 * 30)
            customer.last_login_at = timezone.now()
            customer.save(update_fields=["last_login_at"])
            return Response(_serialize_customer(customer), status=201)
        except Exception as e:
            import logging
            logging.getLogger(__name__).exception("MenuCustomer register failed")
            msg = str(e)
            low = msg.lower()
            if "unique" in low or "duplicate" in low:
                if "email" in low:
                    return Response({"detail": "email_already_registered"}, status=409)
                if "phone" in low:
                    return Response({"detail": "phone_already_registered"}, status=409)
            return Response({"detail": "server_error", "message": msg}, status=500)


class CustomerLoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        identifier = (request.data.get("identifier") or request.data.get("email") or request.data.get("phone") or "").strip()
        password = (request.data.get("password") or "").strip()
        if not identifier or not password:
            return Response({"detail": "credentials_required"}, status=400)

        customer = None
        if "@" in identifier:
            customer = MenuCustomer.objects.filter(email__iexact=identifier.lower(), is_active=True).first()
        else:
            phone = _normalize_phone(identifier)
            if phone:
                customer = MenuCustomer.objects.filter(phone=phone, is_active=True).first()

        if not customer or not customer.check_password(password):
            return Response({"detail": "invalid_credentials"}, status=401)

        request.session[SESSION_KEY] = customer.id
        request.session.set_expiry(60 * 60 * 24 * 30)
        customer.last_login_at = timezone.now()
        customer.save(update_fields=["last_login_at"])
        return Response(_serialize_customer(customer))


class CustomerForgotPasswordView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        import random
        from django.core.cache import cache
        email = (request.data.get("email") or "").strip().lower()
        if not _valid_email(email):
            return Response({"detail": "invalid_email"}, status=400)
        customer = MenuCustomer.objects.filter(email__iexact=email, is_active=True).first()
        if not customer:
            # Do not leak account existence.
            return Response({"detail": "code_sent"})
        code = str(random.randint(100000, 999999))
        cache.set(f"menu_customer_reset_{email}", code, 600)

        subject = "Your password reset code"
        body = (
            f"Hello,\n\nYour password reset code is: {code}\n\n"
            "This code is valid for 10 minutes.\n\n"
            "If you did not request this, please ignore this email."
        )
        try:
            from django.conf import settings as _s
            from django.core.mail import EmailMessage, get_connection
            from_email = getattr(_s, "BONUS_FROM_EMAIL", getattr(_s, "DEFAULT_FROM_EMAIL", None))
            connection = get_connection(
                backend="django.core.mail.backends.smtp.EmailBackend",
                host=getattr(_s, "BONUS_EMAIL_HOST", _s.EMAIL_HOST),
                port=getattr(_s, "BONUS_EMAIL_PORT", getattr(_s, "EMAIL_PORT", 587)),
                username=getattr(_s, "BONUS_EMAIL_HOST_USER", getattr(_s, "EMAIL_HOST_USER", "")),
                password=getattr(_s, "BONUS_EMAIL_HOST_PASSWORD", getattr(_s, "EMAIL_HOST_PASSWORD", "")),
                use_tls=getattr(_s, "BONUS_EMAIL_USE_TLS", getattr(_s, "EMAIL_USE_TLS", True)),
                timeout=30,
            )
            EmailMessage(subject=subject, body=body, from_email=from_email, to=[email], connection=connection).send(fail_silently=False)
        except Exception:
            import logging
            logging.getLogger(__name__).warning("Password reset email failed for %s", email, exc_info=True)
        return Response({"detail": "code_sent"})


class CustomerResetPasswordView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        from django.core.cache import cache
        email = (request.data.get("email") or "").strip().lower()
        code = (request.data.get("code") or "").strip()
        new_password = (request.data.get("new_password") or "").strip()
        if not _valid_email(email) or not code:
            return Response({"detail": "invalid_input"}, status=400)
        if len(new_password) < 6:
            return Response({"detail": "password_min_6"}, status=400)
        cache_key = f"menu_customer_reset_{email}"
        stored = cache.get(cache_key)
        if not stored or stored != code:
            return Response({"detail": "invalid_or_expired_code"}, status=400)
        customer = MenuCustomer.objects.filter(email__iexact=email, is_active=True).first()
        if not customer:
            return Response({"detail": "invalid_or_expired_code"}, status=400)
        customer.set_password(new_password)
        customer.save(update_fields=["password", "updated_at"])
        cache.delete(cache_key)
        return Response({"detail": "password_reset"})


class CustomerLogoutView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        request.session.pop(SESSION_KEY, None)
        return Response({"detail": "logged_out"})


class CustomerMeView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        c = _get_logged_in_customer(request)
        if not c:
            return Response({"detail": "not_authenticated"}, status=401)
        return Response(_serialize_customer(c))

    def patch(self, request):
        c = _get_logged_in_customer(request)
        if not c:
            return Response({"detail": "not_authenticated"}, status=401)
        fields = []
        if "first_name" in request.data:
            c.first_name = (request.data.get("first_name") or "").strip()
            fields.append("first_name")
        if "last_name" in request.data:
            c.last_name = (request.data.get("last_name") or "").strip()
            fields.append("last_name")
        if "email" in request.data:
            email = (request.data.get("email") or "").strip().lower()
            if not _valid_email(email):
                return Response({"detail": "invalid_email"}, status=400)
            if MenuCustomer.objects.filter(email__iexact=email).exclude(pk=c.pk).exists():
                return Response({"detail": "email_already_registered"}, status=409)
            c.email = email
            fields.append("email")
        if "phone" in request.data:
            phone = _normalize_phone(request.data.get("phone"))
            if not phone:
                return Response({"detail": "phone_required"}, status=400)
            if MenuCustomer.objects.filter(phone=phone).exclude(pk=c.pk).exists():
                return Response({"detail": "phone_already_registered"}, status=409)
            c.phone = phone
            fields.append("phone")
        if "password" in request.data:
            pw = (request.data.get("password") or "").strip()
            if len(pw) < 6:
                return Response({"detail": "password_min_6"}, status=400)
            c.set_password(pw)
            fields.append("password")
        if fields:
            c.save(update_fields=fields + ["updated_at"])
        return Response(_serialize_customer(c))


class CustomerAddressListCreateView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        c = _get_logged_in_customer(request)
        if not c:
            return Response({"detail": "not_authenticated"}, status=401)
        return Response({"addresses": [_serialize_address(a) for a in c.addresses.all()]})

    @transaction.atomic
    def post(self, request):
        c = _get_logged_in_customer(request)
        if not c:
            return Response({"detail": "not_authenticated"}, status=401)
        address = (request.data.get("address") or "").strip()
        label = (request.data.get("label") or "").strip()
        is_default = bool(request.data.get("is_default"))
        if not address:
            return Response({"detail": "address_required"}, status=400)
        if is_default:
            c.addresses.filter(is_default=True).update(is_default=False)
        if not c.addresses.exists():
            is_default = True
        a = MenuCustomerAddress.objects.create(
            customer=c,
            address=address,
            label=label,
            is_default=is_default,
        )
        return Response(_serialize_address(a), status=201)


class CustomerAddressDetailView(APIView):
    permission_classes = [AllowAny]

    def _get(self, request, address_id):
        c = _get_logged_in_customer(request)
        if not c:
            return None, None, Response({"detail": "not_authenticated"}, status=401)
        try:
            a = c.addresses.get(pk=address_id)
        except MenuCustomerAddress.DoesNotExist:
            return None, None, Response({"detail": "not_found"}, status=404)
        return c, a, None

    @transaction.atomic
    def patch(self, request, address_id):
        c, a, err = self._get(request, address_id)
        if err:
            return err
        if "address" in request.data:
            a.address = (request.data.get("address") or "").strip()
        if "label" in request.data:
            a.label = (request.data.get("label") or "").strip()
        if "is_default" in request.data:
            want_default = bool(request.data.get("is_default"))
            if want_default:
                c.addresses.exclude(pk=a.pk).filter(is_default=True).update(is_default=False)
            a.is_default = want_default
        a.save()
        return Response(_serialize_address(a))

    def delete(self, request, address_id):
        c, a, err = self._get(request, address_id)
        if err:
            return err
        was_default = a.is_default
        a.delete()
        if was_default:
            other = c.addresses.first()
            if other and not other.is_default:
                other.is_default = True
                other.save(update_fields=["is_default"])
        return Response(status=204)
