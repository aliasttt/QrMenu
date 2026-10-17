"""Password-confirmed business account erasure and detached accounting retention."""

import json
import logging
import re
from urllib.parse import unquote, urlsplit

from django.conf import settings
from django.contrib.admin.models import LogEntry
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.contrib.sessions.models import Session
from django.core.files.storage import default_storage
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db.models.deletion import Collector
from django.db.models import FileField, Q
from django.utils import timezone
from rest_framework import permissions
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken
from rest_framework_simplejwt.models import TokenUser
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

from .models import (
    AccountMediaDeletion, BusinessAdmin, CloudinaryImage, MenuItemImage, Order,
    Package, Payment, PendingEmailVerification, ReservationSettings,
    Restaurant, RetainedFinancialRecord,
)

logger = logging.getLogger(__name__)


class ActiveUserTokenRefreshSerializer(TokenRefreshSerializer):
    def validate(self, attrs):
        # Older SimpleJWT releases can refresh tokens belonging to deleted users.
        refresh = self.token_class(attrs["refresh"])
        with transaction.atomic():
            user = User.objects.select_for_update().filter(
                pk=refresh[api_settings.USER_ID_CLAIM], is_active=True,
            ).first()
            if user is None:
                raise AuthenticationFailed("User not found or inactive", code="user_inactive")
            return super().validate(attrs)


class DeletionAuthentication(JWTAuthentication):
    def get_user(self, validated_token):
        # Signature, expiry and access-token type are still checked by JWTAuthentication.
        try:
            user = User.objects.filter(pk=validated_token[api_settings.USER_ID_CLAIM]).first()
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidToken("Token contained no recognizable user identification") from exc
        if user is None:
            return TokenUser(validated_token)
        if not user.is_active:
            raise AuthenticationFailed("User is inactive", code="user_inactive")
        return user


def purge_account_media():
    """External failures leave a durable retry, never restore a deleted account."""
    failed = 0
    for entry in AccountMediaDeletion.objects.all().iterator():
        try:
            if entry.backend == "cloudinary":
                import cloudinary.uploader

                result = cloudinary.uploader.destroy(entry.name, invalidate=True)
                if result.get("result") not in {"ok", "not found"}:
                    raise RuntimeError("Media deletion was not acknowledged")
            else:
                default_storage.delete(entry.name)
            entry.delete()
        except Exception:
            failed += 1
            logger.warning("account_media_cleanup_failed job_id=%s", entry.pk)
    return failed


def _queue_url(url, restaurant_id):
    """Only remove uploads in our storage namespace; never fetch user supplied URLs."""
    if not isinstance(url, str) or not url:
        return
    parsed = urlsplit(url)
    media = urlsplit(settings.MEDIA_URL)
    if parsed.path.startswith(media.path):
        name = unquote(parsed.path[len(media.path):])
        if name.startswith(f"restaurants/{restaurant_id}/gallery/") and ".." not in name.split("/"):
            AccountMediaDeletion.objects.get_or_create(backend="storage", name=name)
        return
    prefix = f"/{settings.CLOUDINARY_CLOUD_NAME}/image/upload/"
    if settings.CLOUDINARY_CLOUD_NAME and parsed.netloc == "res.cloudinary.com" and parsed.path.startswith(prefix):
        name = parsed.path[len(prefix):]
        # Uploaded URLs may include a version, but not arbitrary transformation paths.
        name = re.sub(r"^v\d+/", "", name)
        name = name.rsplit(".", 1)[0]
        name = unquote(name)
        # Storage may prepend MEDIA_URL to its public ID.
        relative = name.removeprefix(media.path.strip("/") + "/")
        if relative.startswith(f"restaurants/{restaurant_id}/gallery/") and ".." not in name.split("/"):
            AccountMediaDeletion.objects.get_or_create(backend="cloudinary", name=name)


def _retain_financials(restaurant):
    fields = {
        Order: ("status", "total_amount", "currency", "payment_method", "service_type", "created_at"),
        Payment: ("status", "amount", "currency", "refund_status", "refund_amount", "created_at",
                  "stripe_payment_intent_id", "stripe_charge_id", "stripe_refund_id"),
    }
    for model, names in fields.items():
        for values in model.objects.filter(restaurant=restaurant).values(*names).iterator():
            # Serialize only named accounting fields; never copy notes, addresses or items_json.
            RetainedFinancialRecord.objects.create(
                kind=model.__name__.lower(),
                data=json.loads(json.dumps(values, cls=DjangoJSONEncoder)),
            )


def _queue_media(restaurant):
    instances = [restaurant]
    instances.extend(MenuItemImage.objects.filter(menu_item__restaurant=restaurant))
    instances.extend(Package.objects.filter(restaurant=restaurant))
    instances.extend(ReservationSettings.objects.filter(restaurant=restaurant))
    for instance in instances:
        for field in instance._meta.fields:
            if isinstance(field, FileField):
                value = getattr(instance, field.name)
                if value and value.name:
                    AccountMediaDeletion.objects.get_or_create(backend="storage", name=value.name)
    for url in restaurant.gallery or []:
        _queue_url(url, restaurant.pk)
    images = CloudinaryImage.objects.filter(
        Q(menu_item_images__menu_item__restaurant=restaurant) | Q(owner=restaurant.admin),
    ).distinct()
    for image in images:
        if image.menu_item_images.exclude(menu_item__restaurant=restaurant).exists():
            continue
        AccountMediaDeletion.objects.get_or_create(backend="cloudinary", name=image.cloudinary_public_id)
        image.delete()


class AdminAccountView(APIView):
    authentication_classes = [DeletionAuthentication]
    permission_classes = [permissions.IsAuthenticated]
    http_method_names = ["delete", "options"]

    def delete(self, request):
        password = request.data.get("password") if isinstance(request.data, dict) else None
        if not isinstance(password, str) or not password:
            return Response({"detail": "password_required"}, status=400)
        with transaction.atomic():
            user = User.objects.select_for_update().filter(pk=request.user.pk).first()
            if user is None:
                return Response(status=204)
            if not user.check_password(password):
                return Response({"detail": "invalid_password"}, status=403)
            admin = BusinessAdmin.objects.select_for_update().filter(auth_user=user).first()
            if admin is None:
                return Response({"detail": "business_account_required"}, status=403)
            for token in OutstandingToken.objects.filter(user=user):
                BlacklistedToken.objects.get_or_create(token=token)
            # Tokens contain identity claims; retain only JTIs and expiry for revocation.
            OutstandingToken.objects.filter(user=user).update(token="")
            for session in Session.objects.filter(expire_date__gt=timezone.now()).iterator():
                if str(session.get_decoded().get("_auth_user_id")) == str(user.pk):
                    session.delete()
            # SessionMiddleware must not try to save the just-revoked current session.
            if hasattr(request, "session"):
                request.session.flush()
            PendingEmailVerification.objects.filter(email__iexact=admin.email).delete()
            for restaurant in Restaurant.objects.select_for_update().filter(admin=admin):
                _retain_financials(restaurant)
                _queue_media(restaurant)
            for image in admin.uploaded_images.filter(menu_item_images__isnull=True):
                AccountMediaDeletion.objects.get_or_create(backend="cloudinary", name=image.cloudinary_public_id)
                image.delete()
            # ProviderSubscription uses SET_NULL: preserve refund evidence and immutable purchase claims.
            collector = Collector(using=user._state.db)
            collector.collect([admin])
            collector.collect([user])
            targets = [(model, [obj.pk for obj in objects]) for model, objects in collector.data.items()]
            targets.extend((query.model, query.values_list("pk", flat=True)) for query in collector.fast_deletes)
            for model, identifiers in targets:
                if model._meta.auto_created:
                    continue
                LogEntry.objects.filter(
                    content_type=ContentType.objects.get_for_model(model),
                    object_id__in=[str(value) for value in identifiers],
                ).delete()
            collector.delete()
            transaction.on_commit(purge_account_media)
        return Response(status=204)
