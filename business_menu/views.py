from rest_framework import status, permissions
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from django.shortcuts import get_object_or_404, render
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.db import transaction
from django.db import IntegrityError
from django.conf import settings
from django.utils import timezone
from datetime import timedelta
from django.templatetags.static import static as static_url
import io
import json
import logging
import re
from decimal import Decimal

from business_menu.hours_utils import (
    is_within_opening_hours as _is_within_opening_hours,
    is_datetime_within_hours as _is_datetime_within_hours,
)

import qrcode

logger = logging.getLogger(__name__)

from accounts.twilio_utils import (
    send_otp,
    check_otp,
    format_phone_number,
    UNLIMITED_OTP_PHONES,
    UNLIMITED_OTP_CODES,
)
from accounts.email_utils import send_email_verification_code, verify_email_code
from django.contrib.auth.models import User
from .auth_utils import (
    get_or_create_user_for_business_admin,
    sync_user_from_business_admin,
    normalize_email as normalize_email_lower,
)
from .models import (
    BusinessAdmin,
    Restaurant,
    MenuItem,
    MenuItemImage,
    MenuQRCode,
    Category,
    MenuSet,
    Package,
    PackageItem,
    MenuTheme,
    RestaurantSettings,
    Order,
    Reservation,
)
from .serializers import (
    BusinessAdminSerializer, BusinessAdminUpdateSerializer, RestaurantSerializer, MenuItemSerializer,
    MenuItemCreateSerializer, MenuQRCodeSerializer, LoginSerializer, SendOTPSerializer,
    CategorySerializer, MenuSetSerializer, PackageSerializer, PackageCreateSerializer,
    MenuThemeSerializer, RestaurantSettingsSerializer, RestaurantOwnerRegistrationSerializer,
    normalize_price_value,
)
from .cloudinary_utils import (
    upload_image_to_cloudinary, 
    get_image_url_by_uuid, 
    get_image_by_uuid,
    check_cloudinary_status
)

_BM_ADMIN_USERNAME_PREFIX = "business_admin_"


def _business_admin_phone_from_username(username: str) -> str | None:
    """
    Map Django auth username to BusinessAdmin.phone.
    Supports legacy/suffixed usernames like:
      business_admin_905540225177
      business_admin_905540225177_1
    """
    if not username or not username.startswith(_BM_ADMIN_USERNAME_PREFIX):
        return None
    raw = username[len(_BM_ADMIN_USERNAME_PREFIX) :]
    m = re.match(r"^(\d+)", raw or "")
    if not m:
        return None
    return "+" + m.group(1)


def _get_business_admin_for_user(user) -> BusinessAdmin | None:
    """
    Robust mapping from authenticated Django User -> BusinessAdmin.
    Primary: direct DB relation (BusinessAdmin.auth_user).
    Fallback: legacy mapping via username prefix business_admin_{digits}(_suffix).
    """
    if not user:
        return None

    linked = getattr(user, "business_menu_admin", None)
    if linked and getattr(linked, "is_active", False):
        return linked

    phone = _business_admin_phone_from_username(getattr(user, "username", "") or "")
    if not phone:
        return None
    return BusinessAdmin.objects.filter(phone=phone, is_active=True).first()


def _normalize_items_payload(items_data):
    """
    Normalize `items` coming from multipart/form-data.

    Clients often send JSON in a string field like:
      items='[{"menu_item":29,"quantity":2},{"menu_item":30,"quantity":1}]'
    """
    if items_data is None:
        return None

    if isinstance(items_data, (list, tuple)):
        return list(items_data)

    if isinstance(items_data, str):
        raw = items_data.strip()
        if raw == "":
            return []
        try:
            parsed = json.loads(raw)
        except Exception:
            raise ValueError('items must be a JSON array string like [{"menu_item": 1, "quantity": 2}]')
        if not isinstance(parsed, list):
            raise ValueError("items must be a JSON array")
        return parsed

    raise ValueError("items must be a list or JSON array string")


def _extract_request_value(data, key: str):
    """
    DRF uses MultiValueDict/QueryDict for multipart.
    - `.getlist(key)` returns a list of values (even if there is only one)
    - `.get(key)` returns the last value
    For fields like `items`, clients sometimes send multiple parts, so we need to handle both.
    """
    if data is None:
        return None
    if hasattr(data, "getlist"):
        vals = data.getlist(key)
        if not vals:
            return None
        return vals[0] if len(vals) == 1 else vals
    return data.get(key)


def _request_data_to_plain_dict(data):
    """
    Convert request.data (QueryDict/MultiValueDict) into a plain dict.
    This avoids DRF ListField reading values via `getlist()` and wrapping Python lists again.
    Keeps UploadedFile objects intact.
    """
    if data is None:
        return {}
    if hasattr(data, "keys"):
        return {k: _extract_request_value(data, k) for k in data.keys()}
    return dict(data)


class SendOTPView(APIView):
    """
    Send OTP to admin phone and optional email verification code.
    POST /api/business-menu/send-otp/
    Body: {"phone": "+491234567890"}
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        return Response({
            "success": False,
            "message": "Method not allowed. Use POST with JSON body: {\"phone\": \"+49...\"}",
        }, status=status.HTTP_405_METHOD_NOT_ALLOWED)

    def post(self, request):
        serializer = SendOTPSerializer(data=request.data)
        
        if not serializer.is_valid():
            return Response({
                "success": False,
                "errors": serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)
        
        phone = serializer.validated_data['phone']
        
        # فرمت کردن شماره تلفن
        try:
            formatted_phone = format_phone_number(phone)
        except Exception as e:
            return Response({
                "success": False,
                "message": f"Invalid phone number format: {str(e)}"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Only admins registered manually by superuser can receive OTP.
        try:
            admin = BusinessAdmin.objects.get(phone=formatted_phone, is_active=True)
        except BusinessAdmin.DoesNotExist:
            return Response({
                "success": False,
                "message": "This phone number is not registered as an admin. Please contact the system administrator."
            }, status=status.HTTP_404_NOT_FOUND)
        except BusinessAdmin.MultipleObjectsReturned:
            # Handle duplicate admins (shouldn't happen due to unique constraint, but just in case)
            admin = BusinessAdmin.objects.filter(phone=formatted_phone, is_active=True).first()
            if not admin:
                return Response({
                    "success": False,
                    "message": "This phone number is not registered as an admin. Please contact the system administrator."
                }, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            # Log the actual error for debugging
            logger.error(f"Error checking admin for phone {formatted_phone}: {str(e)}", exc_info=True)
            return Response({
                "success": False,
                "message": f"Error checking admin: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        # ارسال OTP به شماره تلفن از طریق Twilio SMS
        try:
            otp_result = send_otp(formatted_phone)
        except Exception as e:
            return Response({
                "success": False,
                "message": f"Error sending OTP: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        # بررسی اینکه آیا BusinessAdmin دارای ایمیل است
        email_result = None
        target_email = None
        
        # Resolve stable auth user for this admin.
        # Prefer the linked auth user to avoid creating duplicates.
        user = admin.auth_user or get_or_create_user_for_business_admin(
            admin_phone=admin.phone,
            admin_name=admin.name,
            admin_email=admin.email,
        )
        sync_user_from_business_admin(
            user=user,
            admin_phone=admin.phone,
            admin_name=admin.name,
            admin_email=admin.email,
        )
        # Keep the relation stable for future requests (do not rely on username mapping)
        if admin.auth_user_id != user.id:
            admin.auth_user = user
            admin.save(update_fields=["auth_user"])

        admin_email = normalize_email_lower(admin.email)
        if admin_email:
            target_email = admin_email
        
        # اگر BusinessAdmin دارای ایمیل است، کد تأیید به ایمیل بفرست
        if target_email:
            # ارسال کد تأیید به ایمیل
            try:
                email_result = send_email_verification_code(user, target_email)
            except Exception as e:
                # اگر ارسال ایمیل خطا داد، فقط لاگ کن و ادامه بده
                logger.error(f"Error sending verification code to email {target_email}: {str(e)}")
                email_result = {
                    'success': False,
                    'message': f'Error sending verification code to email: {str(e)}'
                }
        
        # آماده‌سازی پاسخ
        response_data = {
            "success": otp_result['success'],
            "message": otp_result.get('message', 'OTP code sent'),
            "status": otp_result.get('status', 'error'),
            "phone": formatted_phone,
            "otp_sent": otp_result['success']
        }
        
        # افزودن اطلاعات ایمیل اگر موجود باشد
        if target_email:
            response_data["email"] = target_email
            if email_result:
                response_data["email_code_sent"] = email_result['success']
                if email_result['success']:
                    response_data["message"] = f"{otp_result.get('message', 'OTP code sent')} and verification code sent to your email"
                else:
                    response_data["email_error"] = email_result.get('message', 'Error sending verification code to email')
        
        if otp_result['success']:
            return Response(response_data, status=status.HTTP_200_OK)
        else:
            return Response({
                "success": False,
                "message": otp_result.get('message', 'Error sending OTP'),
                "status": otp_result.get('status', 'error'),
                "error_code": otp_result.get('error_code')
            }, status=status.HTTP_400_BAD_REQUEST)


class LoginView(APIView):
    """
    لاگین ادمین با شماره تلفن و OTP
    POST /api/business-menu/login/
    Body: {"phone": "+491234567890", "code": "123456"}
    
    در صورت موفقیت، JWT token برمی‌گرداند
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        """اگر درخواست از مرورگر باشد به صفحهٔ HTML لاگین هدایت شود."""
        accept = request.META.get("HTTP_ACCEPT", "")
        if "text/html" in accept:
            from django.shortcuts import redirect
            return redirect("/auth/login/")
        return Response(
            {"detail": "POST to login. Send phone and code (OTP).", "allowed_methods": ["POST", "OPTIONS"]},
            status=status.HTTP_200_OK,
        )

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        
        if not serializer.is_valid():
            return Response({
                "success": False,
                "errors": serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)
        
        phone = serializer.validated_data['phone']
        code = serializer.validated_data['code']
        
        # فرمت کردن شماره تلفن
        try:
            formatted_phone = format_phone_number(phone)
        except Exception as e:
            return Response({
                "success": False,
                "message": f"Invalid phone number format: {str(e)}"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Only admins registered manually by superuser can login.
        try:
            admin = BusinessAdmin.objects.get(phone=formatted_phone, is_active=True)
        except BusinessAdmin.DoesNotExist:
            return Response({
                "success": False,
                "message": "This phone number is not registered as an admin."
            }, status=status.HTTP_404_NOT_FOUND)
        
        # Resolve auth user for this admin (prefer linked to avoid duplicates)
        user = admin.auth_user or get_or_create_user_for_business_admin(
            admin_phone=admin.phone,
            admin_name=admin.name,
            admin_email=admin.email,
        )
        sync_user_from_business_admin(
            user=user,
            admin_phone=admin.phone,
            admin_name=admin.name,
            admin_email=admin.email,
        )
        if admin.auth_user_id != user.id:
            admin.auth_user = user
            admin.save(update_fields=["auth_user"])
        
        # بررسی کد - بدون اولویت، هر کدام درست بود لاگین می‌شود
        verified = False
        verification_method = None
        
        # Test-account shortcut (ONLY for the 20 test admins)
        # - If admin is a known test admin (e.g. created by our scripts), accept 123456.
        # - Also keep the explicit phone whitelist as a fallback.
        admin_email = (admin.email or "").strip().lower()
        admin_name = (admin.name or "").strip().lower()
        is_test_admin = admin_email.endswith("@test.local") or admin_name.startswith("test admin")
        in_unlimited_list = formatted_phone in UNLIMITED_OTP_PHONES and formatted_phone in UNLIMITED_OTP_CODES

        logger.info(
            "Business-menu login OTP precheck: phone=%s in_unlimited=%s is_test_admin=%s",
            formatted_phone,
            in_unlimited_list,
            is_test_admin,
        )

        if (is_test_admin and code == "123456") or (in_unlimited_list and code == UNLIMITED_OTP_CODES.get(formatted_phone)):
            verified = True
            verification_method = "test_account"
            logger.info("Test account OTP verified for %s", formatted_phone)
        
        # اگر اکانت تستی نبود یا کد تستی درست نبود، OTP عادی را چک می‌کنیم
        if not verified:
            # اول OTP تلفن را چک می‌کنیم
            phone_result = check_otp(formatted_phone, code)
            logger.info(f"Phone OTP check result for {formatted_phone}: success={phone_result.get('success')}, approved={phone_result.get('approved')}, message={phone_result.get('message')}")
            
            if phone_result.get('success', False) and phone_result.get('approved', False):
                verified = True
                verification_method = 'phone'
                logger.info(f"Phone OTP verified for {formatted_phone}")
            else:
                # Log why phone OTP failed
                logger.warning(f"Phone OTP failed for {formatted_phone}: {phone_result.get('message', 'Unknown error')}")
                
                # اگر OTP تلفن تایید نشد، کد ایمیل را چک می‌کنیم
                if user.email:
                    email_result = verify_email_code(user, user.email, code)
                    if email_result.get('success', False) and email_result.get('approved', False):
                        verified = True
                        verification_method = 'email'
                        logger.info(f"Email verification code approved for user {user.email}")
                    else:
                        logger.warning(f"Email verification failed: {email_result.get('message', 'Unknown error')}")
                else:
                    logger.warning(f"User {user.username} has no email, cannot verify email code")
        
        # اگر هیچ کدام تایید نشد، خطا بده
        if not verified:
            error_message = "Invalid verification code. Please check your code and try again."
            if user.email:
                error_message = "Invalid verification code. Please check your SMS or email code and try again."
            else:
                error_message = "Invalid verification code. Please check your SMS code and try again."
            
            return Response({
                "success": False,
                "message": error_message
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Allow login if: paid OR (trial and trial not expired)
        now = timezone.now()
        if admin.payment_status == "paid":
            pass  # allow
        elif admin.payment_status == "trial" and admin.trial_ends_at and now < admin.trial_ends_at:
            pass  # allow during trial
        else:
            # unpaid or trial expired
            return Response({
                "success": False,
                "message": "Your trial has ended. Please subscribe to continue using the service.",
                "payment_required": True,
                "admin_id": admin.id,
                "subscribe_url": f"/business-menu/subscribe/?admin_id={admin.id}",
            }, status=status.HTTP_403_FORBIDDEN)
        
        # تولید JWT token
        refresh = RefreshToken.for_user(user)
        
        # دریافت رستوران ادمین (OneToOne relationship)
        try:
            restaurant = admin.restaurant if hasattr(admin, 'restaurant') and admin.restaurant.is_active else None
        except Restaurant.DoesNotExist:
            restaurant = None
        
        # آماده‌سازی response
        response_data = {
            "success": True,
            "message": "Login successful",
            "access": str(refresh.access_token),
            "refresh": str(refresh),
            "user": {
                "id": admin.id,
                "phone": admin.phone,
                "email": admin.email or "",
                "is_active": admin.is_active,
                "created_at": admin.created_at.isoformat() if admin.created_at else None
            }
        }
        
        # اضافه کردن اطلاعات رستوران اگر وجود دارد
        if restaurant:
            response_data["restaurant"] = {
                "id": restaurant.id,
                "name": restaurant.name,
                "phone": restaurant.phone or admin.phone,
                "logo": ""  # اگر فیلد logo دارید، آن را اضافه کنید
            }
        
        return Response(response_data, status=status.HTTP_200_OK)


class RestaurantListCreateView(APIView):
    """
    لیست رستوران‌های ادمین یا ایجاد رستوران جدید
    GET /api/business-menu/restaurants/ - لیست رستوران‌های ادمین
    POST /api/business-menu/restaurants/ - ایجاد رستوران جدید
    """
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request):
        """لیست رستوران‌های ادمین"""
        admin = self._get_admin_from_user(request.user)
        if not admin:
            return Response({
                "success": False,
                "message": "Admin not found"
            }, status=status.HTTP_404_NOT_FOUND)
        
        # Get restaurant for this admin (OneToOne relationship)
        try:
            if hasattr(admin, 'restaurant') and admin.restaurant.is_active:
                restaurants = [admin.restaurant]
            else:
                restaurants = []
        except Restaurant.DoesNotExist:
            restaurants = []
        
        serializer = RestaurantSerializer(restaurants, many=True)
        
        return Response({
            "success": True,
            "restaurants": serializer.data
        }, status=status.HTTP_200_OK)
    
    def post(self, request):
        """ایجاد رستوران جدید"""
        admin = self._get_admin_from_user(request.user)
        if not admin:
            return Response({
                "success": False,
                "message": "Admin not found"
            }, status=status.HTTP_404_NOT_FOUND)
        
        serializer = RestaurantSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(admin=admin)
            return Response({
                "success": True,
                "message": "Restaurant created successfully",
                "restaurant": serializer.data
            }, status=status.HTTP_201_CREATED)
        
        return Response({
            "success": False,
            "errors": serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)
    
    def _get_admin_from_user(self, user):
        """پیدا کردن BusinessAdmin از روی User"""
        return _get_business_admin_for_user(user)


class UpdateProfileView(APIView):
    """
    API برای دریافت و آپدیت پروفایل ادمین (email و phone)
    GET /api/business-menu/update-profile/ - دریافت پروفایل ادمین
    PATCH /api/business-menu/update-profile/ - آپدیت پروفایل ادمین
    Body: {"email": "user@example.com", "phone": "+49123456789"}
    """
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request):
        """دریافت پروفایل ادمین"""
        admin = self._get_admin_from_user(request.user)
        
        if not admin:
            return Response({
                "success": False,
                "message": "Business admin account not found. Please contact support or verify your account."
            }, status=status.HTTP_404_NOT_FOUND)
        
        # Prefer the linked user; if missing, link the current authenticated user.
        # This prevents 404s after phone changes where username-based mapping breaks.
        stable_user = admin.auth_user or request.user
        sync_user_from_business_admin(
            user=stable_user,
            admin_phone=admin.phone,
            admin_name=admin.name,
            admin_email=admin.email,
        )
        if admin.auth_user_id != stable_user.id:
            admin.auth_user = stable_user
            admin.save(update_fields=["auth_user"])

        # If BusinessAdmin email empty but auth user has one, sync it for UI consistency.
        if (not (admin.email or "").strip()) and (stable_user.email or "").strip():
            admin.email = (stable_user.email or "").strip()
            admin.save(update_fields=["email"])

        # برگرداندن اطلاعات کامل با BusinessAdminSerializer
        serializer = BusinessAdminSerializer(admin)
        return Response({
            "success": True,
            "admin": serializer.data
        }, status=status.HTTP_200_OK)
    
    def patch(self, request):
        """آپدیت پروفایل ادمین"""
        # Normalize payload: only apply fields that are actually provided and non-empty
        # This prevents accidental wiping (some mobile clients send empty email/phone on update).
        incoming = request.data or {}
        if isinstance(incoming, dict):
            nested = incoming.get("contact") or incoming.get("contactInformation") or {}
            if isinstance(nested, dict):
                merged = {**incoming, **nested}
            else:
                merged = incoming
        else:
            merged = incoming

        def _first(value):
            if isinstance(value, (list, tuple)):
                return value[0] if value else None
            return value

        email_raw = _first(merged.get("email") or merged.get("Email") or merged.get("contact_email") or merged.get("contactEmail"))
        phone_raw = _first(merged.get("phone") or merged.get("phoneNumber") or merged.get("phone_number") or merged.get("mobile"))

        # First, try to find the current admin
        admin = self._get_admin_from_user(request.user)
        
        # If admin not found, check if phone number is provided and already registered
        if not admin:
            if phone_raw is not None:
                phone_value = str(phone_raw).strip()
                if phone_value:
                    # Try to format phone number
                    formatted_phone = None
                    try:
                        formatted_phone = format_phone_number(phone_value)
                    except Exception:
                        # If formatting fails, use original phone value
                        formatted_phone = phone_value
                    
                    # Check if this phone number is already registered (try both formatted and original)
                    existing_admin = None
                    if formatted_phone:
                        existing_admin = BusinessAdmin.objects.filter(phone=formatted_phone, is_active=True).first()
                    
                    # Also check with original phone value if formatted is different
                    if not existing_admin and phone_value != formatted_phone:
                        existing_admin = BusinessAdmin.objects.filter(phone=phone_value, is_active=True).first()
                    
                    if existing_admin:
                        return Response({
                            "success": False,
                            "message": "Phone number already registered. Please use a different phone number."
                        }, status=status.HTTP_400_BAD_REQUEST)
            
            return Response({
                "success": False,
                "message": "Business admin account not found. Please contact support or verify your account."
            }, status=status.HTTP_404_NOT_FOUND)

        # Check if phone number is provided and already registered to another admin
        if phone_raw is not None:
            phone_value = str(phone_raw).strip()
            if phone_value:
                try:
                    # Format phone number
                    formatted_phone = format_phone_number(phone_value)
                    # Check if this phone number is already registered to another admin
                    existing_admin = BusinessAdmin.objects.filter(phone=formatted_phone, is_active=True).first()
                    if existing_admin and existing_admin.id != admin.id:
                        return Response({
                            "success": False,
                            "message": "Phone number already registered. Please use a different phone number."
                        }, status=status.HTTP_400_BAD_REQUEST)
                except Exception as e:
                    # If phone formatting fails, continue - validation will catch it later
                    pass

        data = {}
        if email_raw is not None:
            email_value = str(email_raw).strip()
            # Protect existing email from being cleared accidentally
            if email_value:
                data["email"] = email_value
        if phone_raw is not None:
            phone_value = str(phone_raw).strip()
            if phone_value:
                data["phone"] = phone_value

        # If client sent nothing useful, return current profile (avoid false "success" with no effect)
        if not data:
            serializer = BusinessAdminSerializer(admin)
            return Response({"success": True, "admin": serializer.data}, status=status.HTTP_200_OK)
        
        serializer = BusinessAdminUpdateSerializer(admin, data=data, partial=True)

        if serializer.is_valid():
            try:
                with transaction.atomic():
                    old_phone = admin.phone
                    updated_admin = serializer.save()
                    updated_admin.refresh_from_db()

                    # Keep the currently authenticated user linked to this admin.
                    # This prevents future 404s even if username can't be updated (conflicts/suffixes).
                    auth_user = request.user
                    sync_user_from_business_admin(
                        user=auth_user,
                        admin_phone=updated_admin.phone,
                        admin_name=updated_admin.name,
                        admin_email=updated_admin.email,
                    )
                    if updated_admin.auth_user_id != auth_user.id:
                        updated_admin.auth_user = auth_user
                        updated_admin.save(update_fields=["auth_user"])

            except IntegrityError as e:
                # Handle duplicate phone/username gracefully (avoid opaque 500 in app)
                error_str = str(e).lower()
                # Check if phone was being updated and if error is related to phone uniqueness
                if "phone" in data and ("phone" in error_str or "unique" in error_str or "duplicate" in error_str):
                    return Response({
                        "success": False,
                        "message": "Phone number already registered. Please use a different phone number."
                    }, status=status.HTTP_400_BAD_REQUEST)
                
                if str(e) == "username_conflict":
                    return Response({
                        "success": False,
                        "message": "Phone number already registered. Please use a different phone number."
                    }, status=status.HTTP_400_BAD_REQUEST)

                # Generic error message for other integrity errors
                return Response({
                    "success": False,
                    "message": "Unable to save. The provided information may already be in use. Please check your input and try again."
                }, status=status.HTTP_400_BAD_REQUEST)

            # برگرداندن اطلاعات کامل با BusinessAdminSerializer
            response_serializer = BusinessAdminSerializer(updated_admin)
            return Response({
                "success": True,
                "message": "Profile updated successfully",
                "admin": response_serializer.data
            }, status=status.HTTP_200_OK)
        
        # Log validation issues to help diagnose mobile payload differences
        try:
            logger.warning("UpdateProfileView validation failed: %s payload=%s", serializer.errors, dict(request.data))
        except Exception:
            logger.warning("UpdateProfileView validation failed: %s", serializer.errors)
        
        # Convert serializer errors to user-friendly messages
        error_messages = []
        if isinstance(serializer.errors, dict):
            for field, errors in serializer.errors.items():
                if isinstance(errors, list):
                    for error in errors:
                        if isinstance(error, str):
                            error_messages.append(f"{field}: {error}")
                        else:
                            error_messages.append(f"{field}: {str(error)}")
                else:
                    error_messages.append(f"{field}: {str(errors)}")
        
        message = "; ".join(error_messages) if error_messages else "Validation error. Please check your input."
        
        return Response({
            "success": False,
            "message": message,
            "errors": serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)
    
    def _get_admin_from_user(self, user):
        """پیدا کردن BusinessAdmin از روی User"""
        return _get_business_admin_for_user(user)

    def put(self, request):
        # Some clients use PUT for updates; treat it as PATCH.
        return self.patch(request)


class MenuItemListCreateView(APIView):
    """
    لیست آیتم‌های منو یا ایجاد آیتم جدید
    GET /api/business-menu/menu-items/?restaurant_id=1 - لیست آیتم‌های منو
    POST /api/business-menu/menu-items/ - ایجاد آیتم منو جدید
    """
    permission_classes = [permissions.IsAuthenticated]


class MenuItemCreateFromAppView(APIView):
    """
    API برای ایجاد آیتم منو از اپ دوم (بدون نیاز به authentication)
    POST /api/business-menu/menu-items/
    Body (multipart/form-data):
    - restaurant: 1
    - name: menu1
    - price: 120
    - present: true (string یا boolean)
    - stock: Available
    - details: dellllllllllllll
    - category: (none) - اختیاری
    - images: [file1, file2, ...]
    """
    permission_classes = [permissions.AllowAny]
    
    @transaction.atomic
    def post(self, request):
        """ایجاد آیتم منو از اپ دوم"""
        try:
            restaurant_id = request.data.get('restaurant')
            
            if not restaurant_id:
                return Response({
                    "success": False,
                    "message": "restaurant is required"
                }, status=status.HTTP_400_BAD_REQUEST)
            
            try:
                restaurant = Restaurant.objects.get(id=restaurant_id, is_active=True)
            except Restaurant.DoesNotExist:
                return Response({
                    "success": False,
                    "message": "Restaurant not found"
                }, status=status.HTTP_404_NOT_FOUND)
            
            # normalize کردن قیمت: تبدیل ویرگول به نقطه برای پشتیبانی از کیبورد iPhone
            # استفاده از تابع موجود برای تبدیل QueryDict به dict معمولی
            data = _request_data_to_plain_dict(request.data)
            
            # normalize کردن قیمت با استفاده از تابع normalize_price_value
            if 'price' in data:
                price_value = data.get('price')
                
                if price_value is not None and price_value != '':
                    # تبدیل به string برای اطمینان
                    if not isinstance(price_value, str):
                        price_value = str(price_value)
                    
                    normalized_price = normalize_price_value(price_value)
                    logger.info(f"Price normalization in view: {repr(price_value)} -> {repr(normalized_price)}")
                    if normalized_price is not None:
                        data['price'] = normalized_price
                    else:
                        # اگر normalize کردن نتیجه‌ای نداد، حذف کن تا validation خطا بدهد
                        logger.warning(f"Price normalization returned None for: {repr(price_value)}")
                        data.pop('price', None)
                else:
                    logger.warning(f"Price is None or empty: {repr(price_value)}")
                    data.pop('price', None)
            
            # Log برای debugging - نمایش همه داده‌ها
            logger.info(f"Creating menu item. Raw request.data type: {type(request.data)}")
            logger.info(f"Creating menu item. Raw request.data: {dict(request.data) if hasattr(request.data, '__iter__') else request.data}")
            logger.info(f"Creating menu item. Normalized data: {data}")
            logger.info(f"Price value in data: {data.get('price')}, type: {type(data.get('price'))}")
            
            serializer = MenuItemCreateSerializer(data=data, context={'request': request})
            if serializer.is_valid():
                try:
                    menu_item = serializer.save(restaurant=restaurant)
                    response_serializer = MenuItemSerializer(menu_item, context={'request': request})
                    
                    # برگرداندن مستقیم داده‌های menu_item بدون wrapper
                    return Response(response_serializer.data, status=status.HTTP_201_CREATED)
                except Exception as save_error:
                    import traceback
                    logger.error(f"Error saving menu item: {str(save_error)}")
                    logger.error(traceback.format_exc())
                    return Response({
                        "success": False,
                        "message": f"Error saving menu item: {str(save_error)}",
                        "error": traceback.format_exc() if settings.DEBUG else None
                    }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
            # Log validation errors for debugging
            logger.warning(f"Menu item validation failed. Errors: {serializer.errors}, Data: {data}")
            
            # Convert serializer errors to user-friendly messages
            error_messages = []
            if isinstance(serializer.errors, dict):
                for field, errors in serializer.errors.items():
                    if isinstance(errors, list):
                        for error in errors:
                            if isinstance(error, str):
                                error_messages.append(f"{field}: {error}")
                            else:
                                error_messages.append(f"{field}: {str(error)}")
                    else:
                        error_messages.append(f"{field}: {str(errors)}")
            
            message = "; ".join(error_messages) if error_messages else "Validation error. Please check your input."
            
            return Response({
                "success": False,
                "message": message,
                "errors": serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            import traceback
            logger.error(f"Error in MenuItemCreateFromAppView.post: {str(e)}")
            logger.error(traceback.format_exc())
            return Response({
                "success": False,
                "message": f"Error creating menu item: {str(e)}",
                "error": traceback.format_exc() if settings.DEBUG else None
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def get(self, request):
        """لیست آیتم‌های منو"""
        restaurant_id = request.query_params.get('restaurant_id')
        
        if not restaurant_id:
            return Response({
                "error": "restaurant_id is required"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            restaurant = Restaurant.objects.get(id=restaurant_id, is_active=True)
        except Restaurant.DoesNotExist:
            return Response({
                "error": "Restaurant not found"
            }, status=status.HTTP_404_NOT_FOUND)
        
        menu_items = MenuItem.objects.filter(restaurant=restaurant).order_by('order', 'name')
        serializer = MenuItemSerializer(menu_items, many=True, context={'request': request})
        
        # برگرداندن لیست مستقیم بدون wrapper
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    @transaction.atomic
    def post(self, request):
        """ایجاد آیتم منو جدید"""
        admin = self._get_admin_from_user(request.user)
        if not admin:
            return Response({
                "success": False,
                "message": "Admin not found"
            }, status=status.HTTP_404_NOT_FOUND)
        
        restaurant_id = request.data.get('restaurant')
        try:
            restaurant = Restaurant.objects.get(id=restaurant_id, admin=admin, is_active=True)
        except Restaurant.DoesNotExist:
            return Response({
                "success": False,
                "message": "Restaurant not found or you do not have access"
            }, status=status.HTTP_404_NOT_FOUND)
        
        serializer = MenuItemCreateSerializer(data=request.data)
        if serializer.is_valid():
            menu_item = serializer.save(restaurant=restaurant)
            response_serializer = MenuItemSerializer(menu_item, context={'request': request})
            
            return Response({
                "success": True,
                "message": "Menu item created successfully",
                "menu_item": response_serializer.data
            }, status=status.HTTP_201_CREATED)
        
        return Response({
            "success": False,
            "errors": serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)
    
    def _get_admin_from_user(self, user):
        """پیدا کردن BusinessAdmin از روی User"""
        return _get_business_admin_for_user(user)


class MenuItemDetailView(APIView):
    """
    API برای به‌روزرسانی و حذف آیتم منو
    PATCH /api/business-menu/menu-items/{id}/ - به‌روزرسانی آیتم منو
    DELETE /api/business-menu/menu-items/{id}/ - حذف آیتم منو
    """
    permission_classes = [permissions.AllowAny]
    
    def get_object(self, pk):
        """دریافت menu item"""
        try:
            return MenuItem.objects.get(pk=pk)
        except MenuItem.DoesNotExist:
            return None
    
    def patch(self, request, pk):
        """به‌روزرسانی آیتم منو"""
        menu_item = self.get_object(pk)
        
        if not menu_item:
            return Response({
                "error": "Menu item not found"
            }, status=status.HTTP_404_NOT_FOUND)

        def _parse_bool(v):
            if isinstance(v, bool):
                return v
            if v is None:
                return False
            if isinstance(v, (int, float)):
                return v != 0
            if isinstance(v, str):
                return v.strip().lower() in ("true", "1", "yes", "on")
            return bool(v)

        def _parse_uuid_list(values):
            """
            Accepts:
            - QueryDict.getlist results (list of strings)
            - JSON string like '["uuid1","uuid2"]'
            - comma-separated string like 'uuid1,uuid2'
            """
            if values is None:
                return []
            if isinstance(values, (list, tuple)):
                return [str(x).strip() for x in values if str(x).strip()]
            if isinstance(values, str):
                raw = values.strip()
                if not raw:
                    return []
                # JSON list
                if raw.startswith("[") and raw.endswith("]"):
                    try:
                        import json
                        parsed = json.loads(raw)
                        if isinstance(parsed, list):
                            return [str(x).strip() for x in parsed if str(x).strip()]
                    except Exception:
                        pass
                # comma-separated
                if "," in raw:
                    return [p.strip() for p in raw.split(",") if p.strip()]
                return [raw]
            return [str(values).strip()]

        # تصاویرِ آپدیتی (multipart/form-data)
        uploaded_images = []
        try:
            uploaded_images.extend(request.FILES.getlist("images"))
        except Exception:
            pass
        try:
            uploaded_images.extend(request.FILES.getlist("images[]"))
        except Exception:
            pass
        # بعضی کلاینت‌ها فقط "image" می‌فرستن
        if "image" in request.FILES:
            uploaded_images.append(request.FILES["image"])

        image_uuid_values = []
        if hasattr(request.data, "getlist"):
            image_uuid_values = request.data.getlist("image_uuids") or request.data.getlist("image_uuids[]")
        if not image_uuid_values:
            image_uuid_values = request.data.get("image_uuids") or request.data.get("image_uuids[]")
        image_uuid_values = _parse_uuid_list(image_uuid_values)

        clear_images = _parse_bool(request.data.get("clear_images") or request.data.get("clearImages"))
        replace_images = _parse_bool(request.data.get("replace_images") or request.data.get("replaceImages"))
        
        # پارس کردن existing_images (لیست URLهای تصاویری که باید نگه داشته شوند)
        existing_images_raw = request.data.get("existing_images") or request.data.get("existingImages")
        existing_image_urls = []
        if existing_images_raw:
            if isinstance(existing_images_raw, str):
                # اگر JSON string است
                if existing_images_raw.strip().startswith("["):
                    try:
                        import json
                        existing_image_urls = json.loads(existing_images_raw)
                    except Exception:
                        pass
                else:
                    # اگر comma-separated است
                    existing_image_urls = [url.strip() for url in existing_images_raw.split(",") if url.strip()]
            elif isinstance(existing_images_raw, (list, tuple)):
                existing_image_urls = [str(url).strip() for url in existing_images_raw if url]

        # تبدیل فیلدهای اپ به فیلدهای مدل (فقط فیلدهای متنی/عددی)
        data = {}
        for key, value in request.data.items():
            # کلیدهای مربوط به عکس را از serializer عمومی حذف کن
            if key in ("images", "images[]", "image", "image_uuids", "image_uuids[]", "clear_images", "clearImages", "replace_images", "replaceImages", "existing_images", "existingImages"):
                continue
            if isinstance(value, list) and len(value) > 0:
                data[key] = value[0]
            elif isinstance(value, list) and len(value) == 0:
                continue
            else:
                data[key] = value

        # حذف restaurant چون read-only است
        data.pop("restaurant", None)

        # present/details/price mapping (MenuItemSerializer هم mapping دارد، ولی اینجا هم نگه می‌داریم)
        if "present" in data:
            present_value = data.pop("present")
            if isinstance(present_value, str):
                data["is_available"] = present_value.lower() in ("true", "1", "yes", "on")
            else:
                data["is_available"] = bool(present_value)
        elif "present" in request.data:
            # اگر در data نبود، از request.data بگیر
            present_value = request.data.get("present")
            if present_value is not None:
                if isinstance(present_value, list) and len(present_value) > 0:
                    present_value = present_value[0]
                if isinstance(present_value, str):
                    data["is_available"] = present_value.lower() in ("true", "1", "yes", "on")
                else:
                    data["is_available"] = bool(present_value)
        
        if "details" in data:
            data["description"] = data.pop("details")
        elif "details" in request.data:
            # اگر در data نبود، از request.data بگیر
            details_value = request.data.get("details")
            if details_value is not None:
                if isinstance(details_value, list) and len(details_value) > 0:
                    details_value = details_value[0]
                data["description"] = str(details_value) if details_value else ""
        
        # پردازش price (تبدیل به price_value برای serializer)
        if "price" in data:
            price_value = data.pop("price")
            if price_value is not None:
                try:
                    from decimal import Decimal
                    # استفاده از تابع normalize_price_value برای normalize کردن
                    normalized_price = normalize_price_value(price_value)
                    if normalized_price is not None:
                        data["price_value"] = Decimal(normalized_price)
                except (ValueError, TypeError, Exception):
                    pass  # اگر تبدیل نشد، serializer خودش handle می‌کند
        elif "price" in request.data:
            # اگر در data نبود، از request.data بگیر
            price_value = request.data.get("price")
            if price_value is not None:
                try:
                    from decimal import Decimal
                    # استفاده از تابع normalize_price_value برای normalize کردن
                    normalized_price = normalize_price_value(price_value)
                    if normalized_price is not None:
                        data["price_value"] = Decimal(normalized_price)
                except (ValueError, TypeError, Exception):
                    pass
        
        # پردازش stock (اطمینان از اینکه به درستی پردازش می‌شود)
        if "stock" in request.data:
            stock_value = request.data.get("stock")
            if stock_value is not None:
                if isinstance(stock_value, list):
                    if len(stock_value) > 0:
                        stock_value = stock_value[0]
                    else:
                        stock_value = ""
                data["stock"] = str(stock_value).strip() if stock_value else ""
            else:
                # اگر None است، empty string بگذار
                data["stock"] = ""
        elif "stock" in data:
            # اگر در data است، مطمئن شو که string است
            if isinstance(data["stock"], list):
                if len(data["stock"]) > 0:
                    data["stock"] = str(data["stock"][0]).strip()
                else:
                    data["stock"] = ""
            elif not isinstance(data["stock"], str):
                data["stock"] = str(data["stock"]).strip() if data["stock"] else ""
            else:
                data["stock"] = data["stock"].strip() if data["stock"] else ""
        
        # پردازش category (چون در serializer read-only است، باید دستی پردازش شود)
        category_id = None
        if "category" in data:
            category_value = data.pop("category")
            if category_value is not None:
                if isinstance(category_value, list) and len(category_value) > 0:
                    category_value = category_value[0]
                try:
                    category_id = int(category_value) if category_value else None
                except (ValueError, TypeError):
                    category_id = None
        # همچنین از request.data هم بررسی کن (برای multipart/form-data)
        elif "category" in request.data:
            category_value = request.data.get("category")
            if category_value is not None:
                if isinstance(category_value, list) and len(category_value) > 0:
                    category_value = category_value[0]
                try:
                    category_id = int(category_value) if category_value else None
                except (ValueError, TypeError):
                    category_id = None

        with transaction.atomic():
            serializer = MenuItemSerializer(menu_item, data=data, partial=True, context={"request": request})
            if not serializer.is_valid():
                return Response({"errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

            serializer.save()
            
            # refresh از دیتابیس برای اطمینان از به‌روزرسانی
            menu_item.refresh_from_db()
            
            # به‌روزرسانی is_available و description به صورت دستی (برای اطمینان از به‌روزرسانی)
            # این کار را انجام می‌دهیم چون serializer ممکن است این فیلدها را به درستی به‌روزرسانی نکند
            update_fields = []
            
            # بررسی is_available (present)
            if "is_available" in data:
                menu_item.is_available = data["is_available"]
                update_fields.append("is_available")
            elif "present" in request.data:
                # اگر در data نبود، دوباره از request.data بگیر و تبدیل کن
                present_value = request.data.get("present")
                if present_value is not None:
                    if isinstance(present_value, list) and len(present_value) > 0:
                        present_value = present_value[0]
                    if isinstance(present_value, str):
                        menu_item.is_available = present_value.lower() in ("true", "1", "yes", "on")
                    else:
                        menu_item.is_available = bool(present_value)
                    update_fields.append("is_available")
            
            # بررسی description (details)
            if "description" in data:
                menu_item.description = data["description"]
                update_fields.append("description")
            elif "details" in request.data:
                # اگر در data نبود، دوباره از request.data بگیر و تبدیل کن
                details_value = request.data.get("details")
                if details_value is not None:
                    if isinstance(details_value, list) and len(details_value) > 0:
                        details_value = details_value[0]
                    menu_item.description = str(details_value) if details_value else ""
                    update_fields.append("description")
            
            if update_fields:
                menu_item.save(update_fields=update_fields)
            
            # به‌روزرسانی category به صورت دستی (چون read-only است)
            if category_id is not None:
                try:
                    from .models import Category
                    if category_id:
                        category_obj = Category.objects.filter(id=category_id, restaurant=menu_item.restaurant).first()
                        menu_item.category = category_obj
                    else:
                        menu_item.category = None
                    menu_item.save(update_fields=['category'])
                except Exception as e:
                    logger.warning(f"Error updating category: {str(e)}")
            elif "category" in request.data:
                # اگر category به صورت صریح null یا empty ارسال شده
                category_value = request.data.get("category")
                if category_value is None or (isinstance(category_value, list) and len(category_value) == 0) or (isinstance(category_value, str) and not category_value.strip()):
                    menu_item.category = None
                    menu_item.save(update_fields=['category'])

            # مدیریت تصاویر
            # اگر clear_images true باشد، همه تصاویر را پاک کن
            if clear_images:
                menu_item.images.all().delete()
            # اگر existing_images ارسال شده (حتی اگر خالی باشد)، فقط تصاویری که در لیست هستند را نگه دار
            elif existing_image_urls is not None:
                # دریافت همه تصاویر فعلی
                current_images = list(menu_item.images.all())
                images_to_keep = []
                
                # normalize کردن لیست existing_image_urls برای مقایسه
                def normalize_url(url):
                    """Normalize URL برای مقایسه"""
                    url_str = str(url).strip()
                    if not url_str:
                        return None
                    # حذف query parameters و trailing slashes
                    normalized = url_str.split('?')[0].rstrip('/')
                    return normalized.lower()
                
                existing_urls_normalized = [normalize_url(url) for url in existing_image_urls if normalize_url(url)]
                
                # پیدا کردن تصاویری که باید نگه داشته شوند
                for img in current_images:
                    img_url = img.get_image_url(request=request, secure=True)
                    should_keep = False
                    
                    if img_url:
                        img_url_normalized = normalize_url(img_url)
                        
                        # مقایسه با لیست existing URLs
                        for existing_normalized in existing_urls_normalized:
                            if existing_normalized and img_url_normalized:
                                # مقایسه دقیق
                                if img_url_normalized == existing_normalized:
                                    should_keep = True
                                    break
                                # مقایسه partial (برای Cloudinary URLs که ممکن است version داشته باشند)
                                if existing_normalized in img_url_normalized or img_url_normalized in existing_normalized:
                                    should_keep = True
                                    break
                    
                    # اگر از طریق URL پیدا نشد، با cloudinary_url مستقیم مقایسه کن
                    if not should_keep and img.cloudinary_image:
                        cloudinary_url = img.cloudinary_image.cloudinary_url or img.cloudinary_image.secure_url
                        if cloudinary_url:
                            cloudinary_normalized = normalize_url(cloudinary_url)
                            for existing_normalized in existing_urls_normalized:
                                if existing_normalized and cloudinary_normalized:
                                    if cloudinary_normalized == existing_normalized or existing_normalized in cloudinary_normalized or cloudinary_normalized in existing_normalized:
                                        should_keep = True
                                        break
                    
                    if should_keep:
                        images_to_keep.append(img.id)
                
                # حذف تصاویری که در لیست existing_images نیستند
                menu_item.images.exclude(id__in=images_to_keep).delete()
            # اگر replace_images true باشد و existing_images نباشد، همه را پاک کن
            elif replace_images:
                menu_item.images.all().delete()

            # اضافه کردن تصاویر جدید (فایل‌ها و UUIDها)
            if uploaded_images or image_uuid_values:
                # شمارش تصاویر باقی‌مانده برای order
                start_order = menu_item.images.count()

                # فایل‌های جدید
                for idx, image_file in enumerate(uploaded_images):
                    try:
                        upload_result = upload_image_to_cloudinary(image_file)
                        if upload_result.get("success") and upload_result.get("cloudinary_image"):
                            MenuItemImage.objects.create(
                                menu_item=menu_item,
                                cloudinary_image=upload_result["cloudinary_image"],
                                order=start_order + idx,
                            )
                        else:
                            MenuItemImage.objects.create(
                                menu_item=menu_item,
                                image=image_file,
                                order=start_order + idx,
                            )
                    except Exception:
                        # اگر آپلود خطا داد، request را fail نکن
                        try:
                            MenuItemImage.objects.create(
                                menu_item=menu_item,
                                image=image_file,
                                order=start_order + idx,
                            )
                        except Exception:
                            pass

                # UUIDهای جدید (از قبل آپلود شده)
                uuid_start = start_order + len(uploaded_images)
                for idx, uuid_str in enumerate(image_uuid_values):
                    try:
                        cloudinary_image = get_image_by_uuid(uuid_str)
                        if cloudinary_image:
                            MenuItemImage.objects.create(
                                menu_item=menu_item,
                                cloudinary_image=cloudinary_image,
                                order=uuid_start + idx,
                            )
                    except Exception:
                        pass

            # Reload so serializer sees new related images and updated fields
            menu_item.refresh_from_db()
            response_serializer = MenuItemSerializer(menu_item, context={"request": request})
            return Response(response_serializer.data, status=status.HTTP_200_OK)
    
    def delete(self, request, pk):
        """حذف آیتم منو"""
        menu_item = self.get_object(pk)
        
        if not menu_item:
            return Response({
                "error": "Menu item not found"
            }, status=status.HTTP_404_NOT_FOUND)
        
        menu_item.delete()
        
        return Response({
            "success": True,
            "message": "Menu item deleted successfully"
        }, status=status.HTTP_200_OK)


class SaveMenuFromAppView(APIView):
    """
    API برای دریافت منو از اپ و ذخیره آن
    POST /api/business-menu/save-menu-from-app/
    Body: {
        "restaurant_id": 1,
        "menu_items": [
            {
                "name": "پیتزا",
                "price": "12.50",
                "present": "true",
                "stock": "موجود",
                "details": "توضیحات",
                "images": ["url1", "url2"]
            }
        ]
    }
    """
    permission_classes = [permissions.IsAuthenticated]
    
    @transaction.atomic
    def post(self, request):
        """ذخیره منو از اپ"""
        admin = self._get_admin_from_user(request.user)
        if not admin:
            return Response({
                "success": False,
                "message": "Admin not found"
            }, status=status.HTTP_404_NOT_FOUND)
        
        restaurant_id = request.data.get('restaurant_id')
        menu_items_data = request.data.get('menu_items', [])
        
        if not restaurant_id:
            return Response({
                "success": False,
                "message": "restaurant_id is required"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            restaurant = Restaurant.objects.get(id=restaurant_id, admin=admin, is_active=True)
        except Restaurant.DoesNotExist:
            return Response({
                "success": False,
                "message": "Restaurant not found or you do not have access"
            }, status=status.HTTP_404_NOT_FOUND)
        
        # حذف آیتم‌های قبلی (اختیاری - می‌توانید این را حذف کنید)
        # MenuItem.objects.filter(restaurant=restaurant).delete()
        
        saved_items = []
        for index, item_data in enumerate(menu_items_data):
            # تبدیل present از string به boolean
            is_available = item_data.get('present', 'true').lower() == 'true'
            
            # پردازش قیمت: استفاده از تابع normalize_price_value
            price_value = item_data.get('price', '0')
            normalized_price = normalize_price_value(price_value)
            if normalized_price is None:
                normalized_price = '0'  # مقدار پیش‌فرض اگر normalize کردن نتیجه‌ای نداد
            
            from decimal import Decimal
            try:
                price_decimal = Decimal(normalized_price)
            except (ValueError, TypeError):
                price_decimal = Decimal('0')
            
            menu_item = MenuItem.objects.create(
                restaurant=restaurant,
                name=item_data.get('name', ''),
                description=item_data.get('details', ''),
                price=price_decimal,
                stock=item_data.get('stock', ''),
                is_available=is_available,
                order=index
            )
            
            # ذخیره عکس‌ها
            images_urls = item_data.get('images', [])
            for img_index, img_url in enumerate(images_urls):
                # در اینجا باید عکس را از URL دانلود و ذخیره کنید
                # برای سادگی، فقط URL را ذخیره می‌کنیم
                # در production باید عکس را دانلود و در media ذخیره کنید
                MenuItemImage.objects.create(
                    menu_item=menu_item,
                    image=None,  # باید از URL دانلود شود
                    order=img_index
                )
            
            saved_items.append({
                "id": menu_item.id,
                "name": menu_item.name,
                "price": str(menu_item.price),
                "present": menu_item.is_available,
                "stock": menu_item.stock,
                "details": menu_item.description
            })
        
        return Response({
            "success": True,
            "message": f"{len(saved_items)} menu item(s) saved successfully",
            "saved_items": saved_items
        }, status=status.HTTP_201_CREATED)
    
    def _get_admin_from_user(self, user):
        """پیدا کردن BusinessAdmin از روی User"""
        return _get_business_admin_for_user(user)


class GetMenuAPIView(APIView):
    """
    API برای دریافت منو و عکس‌ها (برای استفاده در اپلیکیشن)
    GET /api/business-menu/get-menu/?restaurant_id=1
    """
    permission_classes = [permissions.AllowAny]
    
    def get(self, request):
        """دریافت منو و عکس‌ها"""
        restaurant_id = request.query_params.get('restaurant_id')
        
        if not restaurant_id:
            return Response({
                "success": False,
                "message": "restaurant_id is required"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            restaurant = Restaurant.objects.get(id=restaurant_id, is_active=True)
        except Restaurant.DoesNotExist:
            return Response({
                "success": False,
                "message": "Restaurant not found"
            }, status=status.HTTP_404_NOT_FOUND)
        
        menu_items = MenuItem.objects.filter(restaurant=restaurant, is_available=True).order_by('order', 'name')
        
        menu_data = []
        for item in menu_items:
            images = []
            image_uuids = []
            for img in item.images.all():
                # اولویت با Cloudinary UUID
                if img.cloudinary_image:
                    images.append(img.cloudinary_image.get_url(secure=True))
                    image_uuids.append(str(img.cloudinary_image.uuid))
                elif img.image:
                    request_url = request.build_absolute_uri(img.image.url) if request else img.image.url
                    images.append(request_url)
            
            menu_data.append({
                "id": item.id,
                "name": item.name,
                "description": item.description,
                "price": str(item.price),
                "stock": item.stock,
                "present": item.is_available,
                "serial": item.serial if item.serial else None,
                "images": images,
                "image_uuids": image_uuids,  # UUIDها برای امنیت بیشتر
                "details": item.description
            })
        
        return Response({
            "success": True,
            "restaurant": {
                "id": restaurant.id,
                "name": restaurant.name,
                "description": restaurant.description,
                "address": restaurant.address,
                "phone": restaurant.phone
            },
            "menu_items": menu_data
        }, status=status.HTTP_200_OK)


class GenerateQRCodeView(APIView):
    """
    تولید QR کد برای منو رستوران
    POST /api/business-menu/generate-qr/
    Body: {"restaurant_id": 1}
    """
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request):
        """تولید یا دریافت QR کد منو"""
        restaurant_id = request.data.get('restaurant_id')
        
        if not restaurant_id:
            return Response({
                "success": False,
                "message": "restaurant_id is required"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        admin = self._get_admin_from_user(request.user)
        if not admin:
            return Response({
                "success": False,
                "message": "Admin not found"
            }, status=status.HTTP_404_NOT_FOUND)
        
        try:
            restaurant = Restaurant.objects.get(id=restaurant_id, admin=admin, is_active=True)
        except Restaurant.DoesNotExist:
            return Response({
                "success": False,
                "message": "Restaurant not found or you do not have access"
            }, status=status.HTTP_404_NOT_FOUND)
        
        # دریافت یا ایجاد QR کد
        menu_qr, created = MenuQRCode.objects.get_or_create(restaurant=restaurant)
        
        # ساخت URL کامل منو و ذخیره در دیتابیس
        base_url = request.build_absolute_uri('/').rstrip('/')
        menu_url = f"{base_url}/business-menu/qr/{menu_qr.token}/"
        
        # ذخیره URL در دیتابیس
        if not menu_qr.menu_url or menu_qr.menu_url != menu_url:
            menu_qr.menu_url = menu_url
            menu_qr.save(update_fields=['menu_url'])
        
        serializer = MenuQRCodeSerializer(menu_qr, context={'request': request})
        
        return Response({
            "success": True,
            "message": "QR code created successfully" if created else "QR code already exists",
            "qr_code": serializer.data,
            "menu_url": menu_url  # URL برای اپ
        }, status=status.HTTP_200_OK)
    
    def _get_admin_from_user(self, user):
        """پیدا کردن BusinessAdmin از روی User"""
        return _get_business_admin_for_user(user)


class GetMenuURLView(APIView):
    """
    دریافت URL منو برای رستوران
    GET /api/business-menu/get-menu-url/?restaurant_id=1
    """
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request):
        """دریافت URL منو"""
        restaurant_id = request.query_params.get('restaurant_id')
        
        if not restaurant_id:
            return Response({
                "success": False,
                "message": "restaurant_id is required"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        admin = self._get_admin_from_user(request.user)
        if not admin:
            return Response({
                "success": False,
                "message": "Admin not found"
            }, status=status.HTTP_404_NOT_FOUND)
        
        try:
            restaurant = Restaurant.objects.get(id=restaurant_id, admin=admin, is_active=True)
        except Restaurant.DoesNotExist:
            return Response({
                "success": False,
                "message": "Restaurant not found or you do not have access"
            }, status=status.HTTP_404_NOT_FOUND)
        
        try:
            menu_qr = MenuQRCode.objects.get(restaurant=restaurant)
            menu_url = menu_qr.menu_url or request.build_absolute_uri(f'/business-menu/qr/{menu_qr.token}/')
            
            return Response({
                "success": True,
                "menu_url": menu_url,
                "token": menu_qr.token
            }, status=status.HTTP_200_OK)
        except MenuQRCode.DoesNotExist:
            return Response({
                "success": False,
                "message": "QR code has not been created for this restaurant. Please generate the QR code first."
            }, status=status.HTTP_404_NOT_FOUND)
    
    def _get_admin_from_user(self, user):
        """Find BusinessAdmin from authenticated user."""
        return _get_business_admin_for_user(user)


class GetQRCodeForAppView(APIView):
    """
    API برای دریافت QR code و URL منو برای اپ
    GET /api/business-menu/qr-code/?restaurant_id=1
    
    این API بدون نیاز به authentication کار می‌کند و برای اپ طراحی شده است.
    """
    permission_classes = [permissions.AllowAny]
    
    def get(self, request):
        """دریافت QR code"""
        restaurant_id = request.query_params.get('restaurant_id')
        
        if not restaurant_id:
            return Response({
                "error": "restaurant_id is required"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        return self._get_qr_code(request, restaurant_id)
    
    def _get_qr_code(self, request, restaurant_id):
        """دریافت یا ایجاد QR code برای رستوران"""
        try:
            restaurant = Restaurant.objects.get(id=restaurant_id, is_active=True)
        except Restaurant.DoesNotExist:
            return Response({
                "error": "Restaurant not found"
            }, status=status.HTTP_404_NOT_FOUND)
        
        # دریافت یا ایجاد QR کد (یونیک و بدون منقضی شدن)
        menu_qr, created = MenuQRCode.objects.get_or_create(restaurant=restaurant)
        
        # ساخت URL کامل منو
        base_url = request.build_absolute_uri('/').rstrip('/')
        menu_url = f"{base_url}/business-menu/qr/{menu_qr.token}/"
        qr_image_url = f"{base_url}/business-menu/qr/{menu_qr.token}.png"
        
        # ذخیره URL در دیتابیس (اگر تغییر کرده باشد)
        if not menu_qr.menu_url or menu_qr.menu_url != menu_url:
            menu_qr.menu_url = menu_url
            menu_qr.save(update_fields=['menu_url'])
        
        return Response({
            "restaurant": {
                "id": restaurant.id,
                "name": restaurant.name,
                "phone": restaurant.phone or ""
            },
            "qr_code": {
                "token": menu_qr.token,
                "menu_url": menu_url,
                "qr_image_url": qr_image_url,
                "created_at": menu_qr.created_at.isoformat() if menu_qr.created_at else None
            }
        }, status=status.HTTP_200_OK)


def _build_menu_cards_and_sections(request, restaurant, menu_items, settings_obj):
    """Build menu_cards, menu_sections, category_list, banner_images (same format as core restaurant_menu)."""
    show_images = settings_obj.show_images if settings_obj else True
    menu_cards = []
    sections_map = {}

    for item in menu_items:
        img_url = None
        if show_images:
            first_img = item.images.first()
            if first_img:
                img_url = first_img.get_image_url(request=request)
        if not img_url:
            img_url = f"https://picsum.photos/seed/menu-{item.id}/640/400"
        category_key = str(item.category.id) if item.category else "other"
        category_name = item.category.name if item.category else "Other"
        menu_cards.append({
            "id": item.id,
            "name": item.name,
            "description": item.description or "",
            "price": item.price,
            "image_url": img_url,
            "category_id": category_key,
            "category_name": category_name,
            "serial": (item.serial or "") if item.serial else "",
            "stock": (item.stock or "").strip() or "Available",
        })
        if category_key not in sections_map:
            sections_map[category_key] = {"id": category_key, "name": category_name, "items": []}
        sections_map[category_key]["items"].append(menu_cards[-1])

    menu_sections = list(sections_map.values())
    category_list = []
    for sec in menu_sections:
        thumb = sec["items"][0]["image_url"] if sec["items"] else ""
        category_list.append({"id": sec["id"], "name": sec["name"], "count": len(sec["items"]), "thumb": thumb})

    banner_images = []
    for card in menu_cards:
        img = card.get("image_url")
        if img and img not in banner_images:
            banner_images.append(img)
        if len(banner_images) >= 3:
            break
    return menu_cards, menu_sections, category_list, banner_images


def menu_qr_display_view(request, token):
    """
    نمایش منو هنگام اسکن QR — از همان قالب و استایل صفحه رستوران‌ها و کافه‌ها استفاده می‌کند.
    GET /business-menu/qr/{token}/
    """
    try:
        menu_qr = MenuQRCode.objects.select_related("restaurant", "restaurant__admin").get(token=token)
        restaurant = menu_qr.restaurant

        settings_obj, _ = RestaurantSettings.objects.get_or_create(
            restaurant=restaurant,
            defaults={
                "show_prices": True,
                "show_images": True,
                "show_descriptions": True,
                "show_serial": False,
            },
        )
        if settings_obj.menu_theme_id is None:
            classic = MenuTheme.objects.filter(slug="classic", is_active=True).first()
            if classic:
                settings_obj.menu_theme = classic
                settings_obj.save(update_fields=["menu_theme"])
        theme_slug = "theme--classic"
        if settings_obj.menu_theme and getattr(settings_obj.menu_theme, "slug", None):
            theme_slug = f"theme--{settings_obj.menu_theme.slug}"

        categories = Category.objects.filter(restaurant=restaurant, is_active=True).order_by("order", "name")
        menu_items = MenuItem.objects.filter(restaurant=restaurant, is_available=True).select_related("category").prefetch_related("images", "images__cloudinary_image")
        
        if settings_obj.show_serial:
            items_with_serial = menu_items.exclude(serial__isnull=True).exclude(serial='')
            if items_with_serial.exists():
                menu_items = menu_items.order_by('serial', 'order', 'name')
            else:
                menu_items = menu_items.order_by('order', 'name')
        else:
            menu_items = menu_items.order_by('order', 'name')

        menu_cards, menu_sections, category_list, banner_images = _build_menu_cards_and_sections(
            request, restaurant, list(menu_items), settings_obj
        )

        packages = Package.objects.filter(restaurant=restaurant, is_active=True).order_by('-created_at')
        packages_list = []
        for package in packages:
            all_available = all(
                pmi.menu_item.is_available for pmi in package.package_items.select_related("menu_item").all()
            )
            if not all_available:
                continue
            package_image = None
            if package.image:
                try:
                    package_image = request.build_absolute_uri(package.image.url)
                except Exception:
                    pass
            packages_list.append({
                'id': package.id,
                'name': package.name,
                'description': package.description or '',
                'original_price': str(package.original_price),
                'package_price': str(package.package_price),
                'discount_percent': getattr(package, 'discount_percent', None) or package.calculate_discount_percent(),
                'image': package_image,
            })

        restaurant_hours = getattr(restaurant, "hours", None) or ""
        return render(
            request,
            'pages/restaurant_menu.html',
            {
                'restaurant': restaurant,
                'restaurant_hours': restaurant_hours,
                'menu_cards': menu_cards,
                'menu_sections': menu_sections,
                'category_list': category_list,
                'banner_images': banner_images,
                'theme_slug': theme_slug,
                'settings': settings_obj,
                'packages': packages_list,
                'is_qr_menu': True,
                'token': token,
                'menu_url': request.build_absolute_uri(request.path),
            },
        )
    except MenuQRCode.DoesNotExist:
        return render(request, 'business_menu/menu_not_found.html', status=404)


class MenuThemeListView(APIView):
    """
    GET /api/business-menu/menu-themes/
    لیست تم‌های منو با preview image
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        themes = MenuTheme.objects.filter(is_active=True).order_by("id")
        serializer = MenuThemeSerializer(themes, many=True, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)


class RestaurantSettingsDetailView(APIView):
    """
    GET  /api/business-menu/restaurant-settings/{restaurant_id}/
    PATCH /api/business-menu/restaurant-settings/{restaurant_id}/
    """
    permission_classes = [permissions.IsAuthenticated]

    def _get_admin_from_user(self, user):
        """پیدا کردن BusinessAdmin از روی User"""
        return _get_business_admin_for_user(user)

    def _get_restaurant(self, request, restaurant_id: int):
        admin = self._get_admin_from_user(request.user)
        if not admin:
            return None
        try:
            return Restaurant.objects.get(id=restaurant_id, admin=admin, is_active=True)
        except Restaurant.DoesNotExist:
            return None

    def get(self, request, restaurant_id: int):
        restaurant = self._get_restaurant(request, restaurant_id)
        if not restaurant:
            return Response({"detail": "Restaurant not found"}, status=status.HTTP_404_NOT_FOUND)

        settings_obj, _ = RestaurantSettings.objects.get_or_create(
            restaurant=restaurant,
            defaults={
                "show_prices": True,
                "show_images": True,
                "show_descriptions": True,
                "show_serial": False,
                "has_delivery": False,
                "allow_payment_cash": True,
                "allow_payment_online": True,
            },
        )

        # Default theme if not set
        if settings_obj.menu_theme is None:
            classic = MenuTheme.objects.filter(slug="classic", is_active=True).first()
            if classic:
                settings_obj.menu_theme = classic
                settings_obj.save(update_fields=["menu_theme"])

        serializer = RestaurantSettingsSerializer(settings_obj)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def patch(self, request, restaurant_id: int):
        restaurant = self._get_restaurant(request, restaurant_id)
        if not restaurant:
            return Response({"detail": "Restaurant not found"}, status=status.HTTP_404_NOT_FOUND)

        settings_obj, _ = RestaurantSettings.objects.get_or_create(
            restaurant=restaurant,
            defaults={
                "show_prices": True,
                "show_images": True,
                "show_descriptions": True,
                "show_serial": False,
                "has_delivery": False,
                "allow_payment_cash": True,
                "allow_payment_online": True,
            },
        )

        serializer = RestaurantSettingsSerializer(settings_obj, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


def _get_restaurant_for_public(request):
    """
    رستوران را از token (QR منو) یا restaurant_id برمی‌گرداند.
    برای APIهای عمومی (سبد، سفارش، گزینه‌های سفارش) بدون احراز هویت.
    Returns: (restaurant, None) or (None, Response)
    """
    token = request.data.get("token") if request.data else None
    if not token:
        token = request.query_params.get("token")
    rid = request.data.get("restaurant_id") if request.data else None
    if rid is None:
        rid = request.query_params.get("restaurant_id")
    if token:
        try:
            menu_qr = MenuQRCode.objects.select_related("restaurant").get(token=token)
            restaurant = menu_qr.restaurant
            if not restaurant.is_active:
                return None, Response(
                    {"detail": "Restaurant is not active."},
                    status=status.HTTP_404_NOT_FOUND,
                )
            return restaurant, None
        except MenuQRCode.DoesNotExist:
            return None, Response(
                {"detail": "Invalid menu token."},
                status=status.HTTP_404_NOT_FOUND,
            )
    if rid is not None:
        try:
            restaurant = Restaurant.objects.get(id=int(rid), is_active=True)
            return restaurant, None
        except (Restaurant.DoesNotExist, ValueError, TypeError):
            return None, Response(
                {"detail": "Restaurant not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
    return None, Response(
        {"detail": "Provide 'token' or 'restaurant_id'."},
        status=status.HTTP_400_BAD_REQUEST,
    )


def _cart_key(restaurant_id):
    return f"cart_restaurant_{restaurant_id}"


def _get_cart(request, restaurant_id):
    """سبد خرید از سشن را برمی‌گرداند (لیست آیتم‌ها)."""
    key = _cart_key(restaurant_id)
    return request.session.get(key, [])


def _set_cart(request, restaurant_id, items):
    """سبد را در سشن ذخیره می‌کند."""
    request.session[_cart_key(restaurant_id)] = items
    request.session.modified = True


def _ensure_order_columns():
    """If Order table is missing service_type, table_number, payment_method, session_key (migration not run),
    add them via raw SQL for PostgreSQL so order create does not 500."""
    from django.db import connection
    if connection.vendor != "postgresql":
        return
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'business_menu_order' AND column_name = 'service_type';
        """)
        if cursor.fetchone():
            return
        for sql in [
            "ALTER TABLE business_menu_order ADD COLUMN IF NOT EXISTS service_type varchar(20) DEFAULT 'dine_in';",
            "ALTER TABLE business_menu_order ADD COLUMN IF NOT EXISTS table_number varchar(32) DEFAULT '';",
            "ALTER TABLE business_menu_order ADD COLUMN IF NOT EXISTS payment_method varchar(20) DEFAULT 'cash';",
            "ALTER TABLE business_menu_order ADD COLUMN IF NOT EXISTS session_key varchar(40) DEFAULT '';",
        ]:
            try:
                cursor.execute(sql)
            except Exception:
                pass


@method_decorator(csrf_exempt, name="dispatch")
class CartView(APIView):
    """
    سبد خرید (عمومی، بدون لاگین).
    GET: لیست آیتم‌های سبد + جمع کل
    POST: افزودن آیتم (menu_item_id, quantity)
    PATCH: تغییر تعداد (menu_item_id, quantity)
    DELETE: حذف آیتم (menu_item_id در بدنه یا query)
    پارامتر: token یا restaurant_id
    """
    permission_classes = [permissions.AllowAny]

    def _restaurant(self, request):
        restaurant, err = _get_restaurant_for_public(request)
        return restaurant, err

    def get(self, request):
        restaurant, err = self._restaurant(request)
        if err:
            return err
        items = _get_cart(request, restaurant.id)
        subtotal = sum(
            (item["quantity"] * float(item["price"])) for item in items
        )
        return Response({
            "restaurant_id": restaurant.id,
            "items": items,
            "subtotal": round(subtotal, 2),
            "total": round(subtotal, 2),
        }, status=status.HTTP_200_OK)

    def post(self, request):
        restaurant, err = self._restaurant(request)
        if err:
            return err
        try:
            settings_obj = RestaurantSettings.objects.get(restaurant=restaurant)
            if not _is_within_opening_hours(settings_obj):
                return Response(
                    {"detail": "Ordering is only available during opening hours. Check the schedule or request a reservation."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        except RestaurantSettings.DoesNotExist:
            pass
        menu_item_id = request.data.get("menu_item_id")
        quantity = request.data.get("quantity", 1)
        if menu_item_id is None:
            return Response(
                {"detail": "menu_item_id is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            quantity = max(1, int(quantity))
        except (TypeError, ValueError):
            quantity = 1
        try:
            item = MenuItem.objects.get(
                id=menu_item_id,
                restaurant=restaurant,
                is_available=True,
            )
        except MenuItem.DoesNotExist:
            return Response(
                {"detail": "Menu item not found or not available."},
                status=status.HTTP_404_NOT_FOUND,
            )
        cart = _get_cart(request, restaurant.id)
        unit_price = str(item.price)
        name = item.name
        for entry in cart:
            if entry.get("menu_item_id") == menu_item_id:
                entry["quantity"] = entry.get("quantity", 0) + quantity
                _set_cart(request, restaurant.id, cart)
                return self.get(request)
        cart.append({
            "menu_item_id": menu_item_id,
            "name": name,
            "price": unit_price,
            "quantity": quantity,
        })
        _set_cart(request, restaurant.id, cart)
        return self.get(request)

    def patch(self, request):
        restaurant, err = self._restaurant(request)
        if err:
            return err
        menu_item_id = request.data.get("menu_item_id")
        quantity = request.data.get("quantity")
        if menu_item_id is None:
            return Response(
                {"detail": "menu_item_id is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            quantity = max(0, int(quantity))
        except (TypeError, ValueError):
            return Response(
                {"detail": "quantity must be a non-negative integer."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        cart = _get_cart(request, restaurant.id)
        for i, entry in enumerate(cart):
            if entry.get("menu_item_id") == menu_item_id:
                if quantity == 0:
                    cart.pop(i)
                else:
                    entry["quantity"] = quantity
                _set_cart(request, restaurant.id, cart)
                return self.get(request)
        return Response(
            {"detail": "Item not in cart."},
            status=status.HTTP_404_NOT_FOUND,
        )

    def delete(self, request):
        restaurant, err = self._restaurant(request)
        if err:
            return err
        menu_item_id = request.data.get("menu_item_id") if request.data else request.query_params.get("menu_item_id")
        if menu_item_id is None:
            return Response(
                {"detail": "menu_item_id is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            menu_item_id = int(menu_item_id)
        except (TypeError, ValueError):
            return Response(
                {"detail": "Invalid menu_item_id."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        cart = _get_cart(request, restaurant.id)
        new_cart = [e for e in cart if e.get("menu_item_id") != menu_item_id]
        if len(new_cart) == len(cart):
            return Response(
                {"detail": "Item not in cart."},
                status=status.HTTP_404_NOT_FOUND,
            )
        _set_cart(request, restaurant.id, new_cart)
        return self.get(request)


class RestaurantOrderOptionsView(APIView):
    """
    گزینه‌های سفارش رستوران برای فرانت (دلیوری فقط اگر فعال باشد).
    GET با token یا restaurant_id — بدون احراز هویت.
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        restaurant, err = _get_restaurant_for_public(request)
        if err:
            return err
        settings_obj, _ = RestaurantSettings.objects.get_or_create(
            restaurant=restaurant,
            defaults={
                "show_prices": True,
                "show_images": True,
                "show_descriptions": True,
                "show_serial": False,
                "has_delivery": False,
                "allow_payment_cash": True,
                "allow_payment_online": True,
            },
        )
        return Response({
            "restaurant_id": restaurant.id,
            "has_delivery": getattr(settings_obj, "has_delivery", False),
            "allow_payment_cash": getattr(settings_obj, "allow_payment_cash", True),
            "allow_payment_online": getattr(settings_obj, "allow_payment_online", True),
        }, status=status.HTTP_200_OK)


@method_decorator(csrf_exempt, name="dispatch")
class OrderCreateView(APIView):
    """
    ثبت سفارش از سبد خرید.
    POST: service_type (dine_in | pickup | delivery), payment_method (cash | online),
          table_number (اختیاری، برای dine_in)، notes
    اگر دلیوری فعال نباشد، delivery قبول نمی‌شود.
    پرداخت آنلاین/نقد طبق تنظیمات رستوران چک می‌شود.
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        restaurant, err = _get_restaurant_for_public(request)
        if err:
            return err
        try:
            _ensure_order_columns()
        except Exception:
            pass
        settings_obj, _ = RestaurantSettings.objects.get_or_create(
            restaurant=restaurant,
            defaults={
                "show_prices": True,
                "show_images": True,
                "show_descriptions": True,
                "show_serial": False,
                "has_delivery": False,
                "allow_payment_cash": True,
                "allow_payment_online": True,
            },
        )
        scheduled_for = (request.data.get("scheduled_for") or "").strip() or None
        scheduled_dt = None
        if scheduled_for:
            try:
                from datetime import datetime
                scheduled_dt = datetime.fromisoformat(scheduled_for.replace("Z", "").split("+")[0].split(".")[0])
                if scheduled_dt <= datetime.now():
                    return Response(
                        {"detail": "scheduled_for must be a future date and time."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                if not _is_datetime_within_hours(settings_obj, scheduled_dt):
                    return Response(
                        {"detail": "Chosen time is outside opening hours."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
            except (ValueError, TypeError):
                return Response(
                    {"detail": "Invalid scheduled_for format. Use ISO format (e.g. 2025-03-10T12:00)."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        elif not _is_within_opening_hours(settings_obj):
            return Response(
                {"detail": "Ordering is only available during opening hours. Check the schedule or request a reservation for another day."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        cart = _get_cart(request, restaurant.id)
        if not cart:
            return Response(
                {"detail": "Cart is empty."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        service_type = (request.data.get("service_type") or "").strip().lower() or "dine_in"
        payment_method = (request.data.get("payment_method") or "").strip().lower() or "cash"
        table_number = (request.data.get("table_number") or "").strip()
        notes = (request.data.get("notes") or "").strip()

        if service_type not in ("dine_in", "pickup", "delivery"):
            return Response(
                {"detail": "Invalid service_type. Use dine_in, pickup, or delivery."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if service_type == "delivery" and not getattr(settings_obj, "has_delivery", False):
            return Response(
                {"detail": "Delivery is not available for this restaurant."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if payment_method not in ("cash", "online"):
            return Response(
                {"detail": "Invalid payment_method. Use cash or online."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if payment_method == "cash" and not getattr(settings_obj, "allow_payment_cash", True):
            return Response(
                {"detail": "Cash payment is not allowed."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if payment_method == "online" and not getattr(settings_obj, "allow_payment_online", True):
            return Response(
                {"detail": "Online payment is not allowed."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if service_type == "dine_in" and not table_number:
            return Response(
                {"detail": "table_number is required for dine-in."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            total = sum(
                (item["quantity"] * float(str(item.get("price", 0)).replace(",", "."))) for item in cart
            )
        except (ValueError, TypeError) as e:
            logger.warning("Order create: invalid cart price %s", e)
            return Response(
                {"detail": "Invalid cart data. Please refresh and try again."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        items_json = [
            {
                "menu_item_id": item.get("menu_item_id"),
                "name": item.get("name", ""),
                "price": str(item.get("price", 0)),
                "quantity": int(item.get("quantity", 1)),
            }
            for item in cart
        ]
        session_key = request.session.session_key or ""
        if not session_key and hasattr(request.session, "create"):
            try:
                request.session.create()
                session_key = request.session.session_key or ""
            except Exception:
                pass

        try:
            total_decimal = Decimal(str(round(total, 2)))
        except Exception:
            total_decimal = Decimal("0.00")
        try:
            with transaction.atomic():
                order = Order.objects.create(
                    restaurant=restaurant,
                    status=Order.Status.PENDING,
                    total_amount=total_decimal,
                    currency="EUR",
                    items_json=items_json,
                    notes=notes,
                    service_type=service_type,
                    table_number=table_number,
                    payment_method=payment_method,
                    session_key=session_key,
                    scheduled_for=scheduled_dt,
                )
            _set_cart(request, restaurant.id, [])
            payload = {
                "order_id": order.id,
                "status": str(order.status),
                "total_amount": str(order.total_amount),
                "currency": str(order.currency),
                "service_type": str(order.service_type),
                "payment_method": str(order.payment_method),
                "table_number": str(order.table_number or ""),
            }
            if payment_method == "online":
                payload["requires_payment"] = True
                payload["payment_url"] = f"/restaurants/{restaurant.id}/order/{order.id}/pay/"
            return Response(payload, status=status.HTTP_201_CREATED)
        except Exception as e:
            logger.exception("Order create failed: %s", e)
            return Response(
                {"detail": "Order could not be created. Please try again."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class OrderListView(APIView):
    """
    لیست سفارشات همین کاربر (با session_key) برای یک رستوران.
    GET با token یا restaurant_id.
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        restaurant, err = _get_restaurant_for_public(request)
        if err:
            return err
        try:
            _ensure_order_columns()
        except Exception:
            pass
        session_key = request.session.session_key or ""
        orders = Order.objects.filter(
            restaurant=restaurant,
            session_key=session_key,
        ).order_by("-created_at")[:50]
        out = []
        for o in orders:
            out.append({
                "id": o.id,
                "status": str(o.status),
                "total_amount": str(o.total_amount),
                "currency": str(o.currency) if o.currency else "EUR",
                "service_type": str(getattr(o, "service_type", "")) or "dine_in",
                "payment_method": str(getattr(o, "payment_method", "")) or "cash",
                "table_number": str(getattr(o, "table_number", "") or ""),
                "created_at": o.created_at.isoformat() if o.created_at else None,
                "items": o.items_json or [],
            })
        return Response({"orders": out}, status=status.HTTP_200_OK)


class AdminOrderListView(APIView):
    """
    لیست سفارشات رستوران برای اپ پنل ادمین.
    فقط ادمین لاگین‌شده (JWT) می‌تواند سفارشات رستوران خودش را ببیند.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        admin = _get_business_admin_for_user(request.user)
        if not admin:
            return Response(
                {"detail": "Business admin not found."},
                status=status.HTTP_403_FORBIDDEN,
            )
        try:
            restaurant = admin.restaurant
        except Restaurant.DoesNotExist:
            return Response(
                {"detail": "Restaurant not found for this admin."},
                status=status.HTTP_404_NOT_FOUND,
            )
        orders = Order.objects.filter(restaurant=restaurant).order_by("-created_at")[:200]
        out = []
        for o in orders:
            out.append({
                "id": o.id,
                "status": o.status,
                "total_amount": str(o.total_amount),
                "currency": o.currency,
                "service_type": o.service_type,
                "payment_method": o.payment_method,
                "table_number": o.table_number or "",
                "notes": o.notes or "",
                "created_at": o.created_at.isoformat() if o.created_at else None,
                "items": o.items_json,
            })
        return Response({
            "restaurant_id": restaurant.id,
            "restaurant_name": restaurant.name,
            "orders": out,
        }, status=status.HTTP_200_OK)


class AdminOrderNewListView(APIView):
    """
    لیست سفارشات جدید (فقط وضعیت pending) برای اپ — برای بخش «New Order».
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        admin = _get_business_admin_for_user(request.user)
        if not admin:
            return Response(
                {"detail": "Business admin not found."},
                status=status.HTTP_403_FORBIDDEN,
            )
        try:
            restaurant = admin.restaurant
        except Restaurant.DoesNotExist:
            return Response(
                {"detail": "Restaurant not found for this admin."},
                status=status.HTTP_404_NOT_FOUND,
            )
        orders = Order.objects.filter(
            restaurant=restaurant,
            status=Order.Status.PENDING,
        ).order_by("-created_at")[:100]
        out = []
        for o in orders:
            out.append({
                "id": o.id,
                "status": o.status,
                "total_amount": str(o.total_amount),
                "currency": o.currency,
                "service_type": o.service_type,
                "payment_method": o.payment_method,
                "table_number": o.table_number or "",
                "notes": o.notes or "",
                "created_at": o.created_at.isoformat() if o.created_at else None,
                "items": o.items_json,
            })
        return Response({
            "restaurant_id": restaurant.id,
            "restaurant_name": restaurant.name,
            "orders": out,
        }, status=status.HTTP_200_OK)


class AdminOrderDetailView(APIView):
    """
    به‌روزرسانی وضعیت سفارش توسط ادمین (Accept / Reject / Prepare / Complete).
    """
    permission_classes = [permissions.IsAuthenticated]

    def _get_admin_restaurant(self, request):
        admin = _get_business_admin_for_user(request.user)
        if not admin:
            return None, Response(
                {"detail": "Business admin not found."},
                status=status.HTTP_403_FORBIDDEN,
            )
        try:
            return admin.restaurant, None
        except Restaurant.DoesNotExist:
            return None, Response(
                {"detail": "Restaurant not found for this admin."},
                status=status.HTTP_404_NOT_FOUND,
            )

    def patch(self, request, order_id):
        restaurant, err = self._get_admin_restaurant(request)
        if err:
            return err
        new_status = (request.data.get("status") or "").strip().lower()
        allowed = ("preparing", "cancelled", "completed", "paid")
        if new_status not in allowed:
            return Response(
                {"detail": f"Invalid status. Use one of: {', '.join(allowed)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            order = Order.objects.get(id=order_id, restaurant=restaurant)
        except Order.DoesNotExist:
            return Response(
                {"detail": "Order not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        order.status = new_status
        order.save(update_fields=["status", "updated_at"])
        return Response({
            "id": order.id,
            "status": order.status,
        }, status=status.HTTP_200_OK)


class AdminOrderSettingsView(APIView):
    """
    تنظیمات سفارش از سمت اپ: دلیوری و روش‌های پرداخت (کش / آنلاین).
    اپ این مقادیر را می‌خواند و از اپ ست می‌کند؛ وب (order-options) همان مقادیر را برای مشتری نشان می‌دهد.
    """
    permission_classes = [permissions.IsAuthenticated]

    def _get_settings(self, request):
        admin = _get_business_admin_for_user(request.user)
        if not admin:
            return None, None, Response(
                {"detail": "Business admin not found."},
                status=status.HTTP_403_FORBIDDEN,
            )
        try:
            restaurant = admin.restaurant
        except Restaurant.DoesNotExist:
            return None, None, Response(
                {"detail": "Restaurant not found for this admin."},
                status=status.HTTP_404_NOT_FOUND,
            )
        settings_obj, _ = RestaurantSettings.objects.get_or_create(
            restaurant=restaurant,
            defaults={
                "show_prices": True,
                "show_images": True,
                "show_descriptions": True,
                "show_serial": False,
                "has_delivery": False,
                "allow_payment_cash": True,
                "allow_payment_online": True,
            },
        )
        return restaurant, settings_obj, None

    def get(self, request):
        restaurant, settings_obj, err = self._get_settings(request)
        if err:
            return err
        return Response({
            "restaurant_id": restaurant.id,
            "restaurant_name": restaurant.name,
            "has_delivery": getattr(settings_obj, "has_delivery", False),
            "allow_payment_cash": getattr(settings_obj, "allow_payment_cash", True),
            "allow_payment_online": getattr(settings_obj, "allow_payment_online", True),
        }, status=status.HTTP_200_OK)

    def patch(self, request):
        restaurant, settings_obj, err = self._get_settings(request)
        if err:
            return err
        data = request.data or {}
        if "has_delivery" in data:
            settings_obj.has_delivery = bool(data["has_delivery"])
        if "allow_payment_cash" in data:
            settings_obj.allow_payment_cash = bool(data["allow_payment_cash"])
        if "allow_payment_online" in data:
            settings_obj.allow_payment_online = bool(data["allow_payment_online"])
        settings_obj.save(update_fields=["has_delivery", "allow_payment_cash", "allow_payment_online", "updated_at"])
        return Response({
            "restaurant_id": restaurant.id,
            "restaurant_name": restaurant.name,
            "has_delivery": settings_obj.has_delivery,
            "allow_payment_cash": settings_obj.allow_payment_cash,
            "allow_payment_online": settings_obj.allow_payment_online,
        }, status=status.HTTP_200_OK)


def menu_qr_image_view(request, token):
    """تولید تصویر QR کد"""
    try:
        menu_qr = MenuQRCode.objects.get(token=token)
        
        # ساخت URL کامل منو
        base_url = request.build_absolute_uri('/').rstrip('/')
        menu_url = f"{base_url}/business-menu/qr/{token}/"
        
        # تولید QR کد
        qr = qrcode.QRCode(version=1, box_size=10, border=2)
        qr.add_data(menu_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        buffer.seek(0)
        
        return HttpResponse(buffer.getvalue(), content_type="image/png")
    except MenuQRCode.DoesNotExist:
        return HttpResponse("QR code not found", status=404)


class ImageUploadView(APIView):
    """
    API برای آپلود تصویر به Cloudinary و دریافت UUID
    POST /api/business-menu/upload-image/
    Body (multipart/form-data):
    - image: [file]
    
    Response:
    {
        "success": true,
        "uuid": "uuid-string",
        "url": "https://...",
        "message": "Image uploaded successfully"
    }
    """
    permission_classes = [permissions.AllowAny]
    
    def post(self, request):
        """آپلود تصویر به Cloudinary"""
        if 'image' not in request.FILES:
            return Response({
                "success": False,
                "message": "No image file provided"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        image_file = request.FILES['image']
        
        # بررسی نوع فایل
        if not image_file.content_type.startswith('image/'):
            return Response({
                "success": False,
                "message": "File must be an image"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # آپلود به Cloudinary
        upload_result = upload_image_to_cloudinary(image_file)
        
        if upload_result['success']:
            return Response({
                "success": True,
                "uuid": upload_result['uuid'],
                "url": upload_result['url'],
                "public_id": upload_result.get('public_id'),
                "message": "Image uploaded successfully and cached on Cloudinary"
            }, status=status.HTTP_201_CREATED)
        else:
            return Response({
                "success": False,
                "message": upload_result.get('error', 'Error uploading image')
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class GetImageByUUIDView(APIView):
    """
    API برای دریافت URL تصویر از روی UUID
    GET /api/business-menu/image/<uuid>/
    """
    permission_classes = [permissions.AllowAny]
    
    def get(self, request, uuid_str):
        """دریافت URL تصویر از روی UUID"""
        cloudinary_image = get_image_by_uuid(uuid_str)
        
        if not cloudinary_image:
            return Response({
                "success": False,
                "message": "Image not found"
            }, status=status.HTTP_404_NOT_FOUND)
        
        return Response({
            "success": True,
            "uuid": str(cloudinary_image.uuid),
            "url": cloudinary_image.get_url(secure=True),
            "public_id": cloudinary_image.cloudinary_public_id,
            "format": cloudinary_image.format,
            "width": cloudinary_image.width,
            "height": cloudinary_image.height,
            "bytes_size": cloudinary_image.bytes_size,
            "created_at": cloudinary_image.created_at
        }, status=status.HTTP_200_OK)


class CloudinaryStatusView(APIView):
    """
    API برای بررسی وضعیت Cloudinary و کش
    GET /api/business-menu/cloudinary-status/
    """
    permission_classes = [permissions.AllowAny]
    
    def get(self, request):
        """بررسی وضعیت Cloudinary"""
        status_info = check_cloudinary_status()
        
        return Response({
            "success": True,
            "status": status_info
        }, status=status.HTTP_200_OK)


class CategoryListCreateView(APIView):
    """
    API برای مدیریت دسته‌بندی‌های منو
    GET /api/business-menu/categories/?restaurant_id=1 - لیست دسته‌بندی‌ها
    POST /api/business-menu/categories/ - ایجاد دسته‌بندی جدید
    """
    permission_classes = [permissions.AllowAny]
    
    def get(self, request):
        """لیست دسته‌بندی‌های منو"""
        restaurant_id = request.query_params.get('restaurant_id')
        
        if not restaurant_id:
            return Response({
                "error": "restaurant_id is required"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            restaurant = Restaurant.objects.get(id=restaurant_id, is_active=True)
        except Restaurant.DoesNotExist:
            return Response({
                "error": "Restaurant not found"
            }, status=status.HTTP_404_NOT_FOUND)
        
        categories = Category.objects.filter(restaurant=restaurant, is_active=True).order_by('order', 'name')
        serializer = CategorySerializer(categories, many=True)
        
        # برگرداندن لیست مستقیم بدون wrapper
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    @transaction.atomic
    def post(self, request):
        """ایجاد دسته‌بندی جدید"""
        data = dict(request.data)
        
        # اگر restaurant در data نیست، از query parameter بگیر
        restaurant_id = data.get('restaurant') or data.get('restaurant_id') or request.query_params.get('restaurant_id')
        phone = data.get('phone') or request.query_params.get('phone')  # شماره تلفن ادمین
        
        restaurant = None
        
        # اگر restaurant_id داده شده، از آن استفاده کن
        if restaurant_id:
            try:
                restaurant = Restaurant.objects.get(id=restaurant_id, is_active=True)
            except Restaurant.DoesNotExist:
                pass
        
        # اگر رستوران پیدا نشد و phone داده شده، از phone ادمین را پیدا کن و رستوران ایجاد کن
        if not restaurant and phone:
            try:
                formatted_phone = format_phone_number(phone)
                admin, _ = BusinessAdmin.objects.get_or_create(
                    phone=formatted_phone,
                    defaults={
                        'name': f'Admin {formatted_phone}',
                        'is_active': True
                    }
                )
                # اولین رستوران فعال ادمین را بگیر یا ایجاد کن
                restaurant, _ = Restaurant.objects.get_or_create(
                    admin=admin,
                    is_active=True,
                    defaults={
                        'name': f'Restaurant {admin.name}',
                        'description': 'Default restaurant'
                    }
                )
            except Exception as e:
                pass
        
        # اگر هنوز رستوران پیدا نشد، خطا بده
        if not restaurant:
            return Response({
                "error": "Restaurant not found. Please provide restaurant or phone."
            }, status=status.HTTP_400_BAD_REQUEST)
        
        data['restaurant'] = restaurant.id
        
        serializer = CategorySerializer(data=data)
        
        if serializer.is_valid():
            category = serializer.save(restaurant=restaurant)
            # برگرداندن مستقیم داده‌های category بدون wrapper
            return Response(CategorySerializer(category).data, status=status.HTTP_201_CREATED)
        
        return Response({
            "errors": serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)


class CategoryDetailView(APIView):
    """
    API برای به‌روزرسانی و حذف دسته‌بندی
    PATCH /api/business-menu/categories/{id}/ - به‌روزرسانی دسته‌بندی
    DELETE /api/business-menu/categories/{id}/ - حذف دسته‌بندی
    """
    permission_classes = [permissions.AllowAny]
    
    def get_object(self, pk, include_inactive=False):
        """دریافت category"""
        try:
            if include_inactive:
                # برای DELETE، همه category ها را شامل می‌شود
                return Category.objects.get(pk=pk)
            else:
                # برای PATCH، فقط active category ها
                return Category.objects.get(pk=pk, is_active=True)
        except Category.DoesNotExist:
            return None
    
    def patch(self, request, pk):
        """به‌روزرسانی دسته‌بندی"""
        category = self.get_object(pk, include_inactive=False)
        
        if not category:
            return Response({
                "error": "Category not found"
            }, status=status.HTTP_404_NOT_FOUND)
        
        serializer = CategorySerializer(category, data=request.data, partial=True)
        
        if serializer.is_valid():
            serializer.save()
            # برگرداندن مستقیم داده‌های category بدون wrapper
            return Response(serializer.data, status=status.HTTP_200_OK)
        
        return Response({
            "errors": serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)
    
    def delete(self, request, pk):
        """حذف دسته‌بندی"""
        # برای DELETE، باید category را حتی اگر is_active=False باشد پیدا کنیم
        try:
            category = Category.objects.get(pk=pk)
        except Category.DoesNotExist:
            return Response({
                "error": "Category not found"
            }, status=status.HTTP_404_NOT_FOUND)
        
        # Hard delete: حذف کامل از دیتابیس
        category.delete()
        
        return Response({
            "success": True,
            "message": "Category deleted successfully"
        }, status=status.HTTP_200_OK)


class MenuSetListCreateView(APIView):
    """
    API برای مدیریت مجموعه‌های منو
    GET /api/business-menu/menu-sets/?restaurant_id=1 - لیست مجموعه‌ها
    POST /api/business-menu/menu-sets/ - ایجاد مجموعه جدید
    """
    permission_classes = [permissions.AllowAny]
    
    def get(self, request):
        """لیست مجموعه‌های منو"""
        restaurant_id = request.query_params.get('restaurant_id')
        
        if not restaurant_id:
            return Response({
                "error": "restaurant_id is required"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            restaurant = Restaurant.objects.get(id=restaurant_id, is_active=True)
        except Restaurant.DoesNotExist:
            return Response({
                "error": "Restaurant not found"
            }, status=status.HTTP_404_NOT_FOUND)
        
        menu_sets = MenuSet.objects.filter(restaurant=restaurant, is_active=True).order_by('order', 'name')
        serializer = MenuSetSerializer(menu_sets, many=True)
        
        # برگرداندن لیست مستقیم بدون wrapper
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    @transaction.atomic
    def post(self, request):
        """ایجاد مجموعه جدید"""
        data = dict(request.data)
        
        # اگر restaurant در data نیست، از query parameter بگیر
        restaurant_id = data.get('restaurant') or data.get('restaurant_id') or request.query_params.get('restaurant_id')
        
        if not restaurant_id:
            return Response({
                "success": False,
                "message": "restaurant or restaurant_id is required"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # بررسی وجود رستوران
        try:
            restaurant = Restaurant.objects.get(id=restaurant_id, is_active=True)
        except Restaurant.DoesNotExist:
            return Response({
                "success": False,
                "message": "Restaurant not found"
            }, status=status.HTTP_404_NOT_FOUND)
        
        data['restaurant'] = restaurant.id
        
        serializer = MenuSetSerializer(data=data)
        
        if serializer.is_valid():
            menu_set = serializer.save(restaurant=restaurant)
            # برگرداندن مستقیم داده‌های menu_set بدون wrapper
            return Response(MenuSetSerializer(menu_set).data, status=status.HTTP_201_CREATED)
        
        return Response({
            "errors": serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)


class MenuSetDetailView(APIView):
    """
    API برای به‌روزرسانی و حذف مجموعه منو
    PATCH /api/business-menu/menu-sets/{id}/ - به‌روزرسانی مجموعه منو
    DELETE /api/business-menu/menu-sets/{id}/ - حذف مجموعه منو
    """
    permission_classes = [permissions.AllowAny]
    
    def get_object(self, pk):
        """دریافت menu set"""
        try:
            return MenuSet.objects.get(pk=pk, is_active=True)
        except MenuSet.DoesNotExist:
            return None
    
    def patch(self, request, pk):
        """به‌روزرسانی مجموعه منو"""
        menu_set = self.get_object(pk)
        
        if not menu_set:
            return Response({
                "error": "Menu set not found"
            }, status=status.HTTP_404_NOT_FOUND)
        
        serializer = MenuSetSerializer(menu_set, data=request.data, partial=True)
        
        if serializer.is_valid():
            serializer.save()
            # برگرداندن مستقیم داده‌های menu_set بدون wrapper
            return Response(serializer.data, status=status.HTTP_200_OK)
        
        return Response({
            "errors": serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)
    
    def delete(self, request, pk):
        """حذف مجموعه منو"""
        menu_set = self.get_object(pk)
        
        if not menu_set:
            return Response({
                "error": "Menu set not found"
            }, status=status.HTTP_404_NOT_FOUND)
        
        # Soft delete: فقط is_active را false کن
        menu_set.is_active = False
        menu_set.save()
        
        return Response({
            "success": True,
            "message": "Menu set deleted successfully"
        }, status=status.HTTP_200_OK)


class PackageListCreateView(APIView):
    """
    API برای مدیریت پکیج‌ها
    GET /api/business-menu/packages/?restaurant_id=1 - لیست پکیج‌ها
    POST /api/business-menu/packages/ - ایجاد پکیج جدید
    """
    permission_classes = [permissions.AllowAny]
    
    def get(self, request):
        """لیست پکیج‌ها"""
        restaurant_id = request.query_params.get('restaurant_id')
        
        if not restaurant_id:
            return Response({
                "success": False,
                "error": "restaurant_id is required"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            restaurant = Restaurant.objects.get(id=restaurant_id, is_active=True)
        except Restaurant.DoesNotExist:
            return Response({
                "success": False,
                "error": "Restaurant not found"
            }, status=status.HTTP_404_NOT_FOUND)
        
        packages = Package.objects.filter(restaurant=restaurant, is_active=True).order_by('-created_at')
        serializer = PackageSerializer(packages, many=True, context={'request': request})
        
        return Response({
            "success": True,
            "data": serializer.data
        }, status=status.HTTP_200_OK)
    
    @transaction.atomic
    def post(self, request):
        """ایجاد پکیج جدید"""
        raw = request.data
        data = _request_data_to_plain_dict(raw)
        
        # اگر restaurant در data نیست، از query parameter بگیر
        restaurant_id = data.get('restaurant') or data.get('restaurant_id') or request.query_params.get('restaurant_id')
        
        if not restaurant_id:
            return Response({
                "success": False,
                "message": "restaurant or restaurant_id is required"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        data['restaurant'] = restaurant_id

        # Normalize items for multipart/form-data (often arrives as a JSON string)
        if 'items' in data or (hasattr(raw, "keys") and 'items' in raw):
            try:
                data['items'] = _normalize_items_payload(_extract_request_value(raw, 'items'))
            except ValueError as e:
                return Response(
                    {"success": False, "errors": {"items": [str(e)]}},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        
        # اگر image به صورت فایل ارسال شده، باید در data باقی بماند
        # PackageCreateSerializer خودش image رو handle می‌کنه
        
        serializer = PackageCreateSerializer(data=data, context={'request': request})
        
        if serializer.is_valid():
            package = serializer.save()
            # برگرداندن با PackageSerializer برای نمایش کامل
            response_serializer = PackageSerializer(package, context={'request': request})
            return Response({
                "success": True,
                "data": response_serializer.data
            }, status=status.HTTP_201_CREATED)
        
        return Response({
            "success": False,
            "errors": serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)


class PackageDetailView(APIView):
    """
    API برای به‌روزرسانی و حذف پکیج
    PATCH /api/business-menu/packages/{id}/ - به‌روزرسانی پکیج
    DELETE /api/business-menu/packages/{id}/ - حذف پکیج
    """
    permission_classes = [permissions.AllowAny]
    
    def get_object(self, pk):
        """دریافت پکیج"""
        try:
            return Package.objects.get(pk=pk, is_active=True)
        except Package.DoesNotExist:
            return None
    
    @transaction.atomic
    def patch(self, request, pk):
        """به‌روزرسانی پکیج"""
        package = self.get_object(pk)
        
        if not package:
            return Response({
                "success": False,
                "error": "Package not found"
            }, status=status.HTTP_404_NOT_FOUND)
        
        raw = request.data
        data = _request_data_to_plain_dict(raw)

        # اگر items در data است، باید آیتم‌های پکیج را به‌روزرسانی کنیم
        items_data = data.pop('items', None)
        if items_data is not None:
            try:
                items_data = _normalize_items_payload(_extract_request_value(raw, 'items'))
            except ValueError as e:
                return Response(
                    {"success": False, "errors": {"items": [str(e)]}},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        
        # اگر image به صورت فایل ارسال شده، باید در data باقی بماند
        # PackageSerializer خودش image رو handle می‌کنه
        
        serializer = PackageSerializer(package, data=data, partial=True, context={'request': request})
        
        if serializer.is_valid():
            serializer.save()
            
            # به‌روزرسانی آیتم‌های پکیج اگر items ارسال شده باشد
            if items_data is not None:
                # حذف آیتم‌های قبلی
                package.package_items.all().delete()
                
                # ایجاد آیتم‌های جدید
                for item_data in items_data:
                    if isinstance(item_data, str):
                        try:
                            item_data = json.loads(item_data)
                        except Exception:
                            continue
                    if not isinstance(item_data, dict):
                        continue
                    menu_item_id = item_data.get('menu_item')
                    quantity = item_data.get('quantity', 1)
                    
                    if menu_item_id:
                        try:
                            quantity = int(quantity) if quantity is not None else 1
                        except Exception:
                            quantity = 1
                        if quantity < 1:
                            quantity = 1
                        try:
                            menu_item = MenuItem.objects.get(id=menu_item_id, restaurant=package.restaurant)
                            PackageItem.objects.create(
                                package=package,
                                menu_item=menu_item,
                                quantity=quantity
                            )
                        except MenuItem.DoesNotExist:
                            pass
            
            # برگرداندن با PackageSerializer برای نمایش کامل
            response_serializer = PackageSerializer(package, context={'request': request})
            return Response({
                "success": True,
                "data": response_serializer.data
            }, status=status.HTTP_200_OK)
        
        return Response({
            "success": False,
            "errors": serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)
    
    def delete(self, request, pk):
        """حذف پکیج (Soft Delete)"""
        package = self.get_object(pk)
        
        if not package:
            return Response({
                "success": False,
                "error": "Package not found"
            }, status=status.HTTP_404_NOT_FOUND)
        
        # Soft delete: فقط is_active را false کن
        package.is_active = False
        package.save()
        
        return Response({
            "success": True,
            "message": "Package deleted successfully"
        }, status=status.HTTP_200_OK)


def menu_themes_preview_view(request):
    """Preview page for menu themes"""
    from django.http import HttpResponse
    import os
    from django.conf import settings
    
    # Read the preview HTML file
    preview_path = os.path.join(settings.BASE_DIR, 'business_menu', 'static', 'business_menu', 'themes', 'preview.html')
    
    try:
        with open(preview_path, 'r', encoding='utf-8') as f:
            html_content = f.read()
        return HttpResponse(html_content, content_type='text/html')
    except FileNotFoundError:
        return HttpResponse('<h1>Preview file not found</h1>', status=404)


class RestaurantOwnerSignupView(APIView):
    """
    Web signup for restaurant owners. Creates account and starts 12-day free trial.
    No payment during trial. Stripe Connect is not active during trial.
    POST /api/business-menu/signup/
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = RestaurantOwnerRegistrationSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"success": False, "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

        validated_data = serializer.validated_data
        from config.sequence_utils import fix_auth_and_signup_sequences

        for attempt in range(2):
            try:
                fix_auth_and_signup_sequences()
                with transaction.atomic():
                    trial_ends_at = timezone.now() + timedelta(days=12)
                    admin = BusinessAdmin.objects.create(
                        phone=validated_data["phone"],
                        name=f"{validated_data['first_name']} {validated_data['last_name']}".strip(),
                        email=validated_data["email"],
                        is_active=True,
                        payment_status="trial",
                        trial_ends_at=trial_ends_at,
                    )
                    base_username = _BM_ADMIN_USERNAME_PREFIX + re.sub(r"\D", "", validated_data["phone"])
                    username = base_username
                    counter = 1
                    while User.objects.filter(username=username).exists():
                        username = f"{base_username}_{counter}"
                        counter += 1
                    user = User.objects.create(
                        username=username,
                        email=validated_data["email"],
                        first_name=validated_data["first_name"],
                        last_name=validated_data["last_name"],
                        is_active=True,
                    )
                    user.set_password(validated_data["password"])
                    user.save()
                    admin.auth_user = user
                    admin.save(update_fields=["auth_user"])

                    restaurant = Restaurant.objects.create(
                        admin=admin,
                        name=validated_data.get("restaurant_name", "").strip() or "My Restaurant",
                        country=validated_data.get("country", "").strip() or "",
                        city=validated_data.get("city", "").strip() or "",
                    )
                    RestaurantSettings.objects.get_or_create(restaurant=restaurant)

                from django.conf import settings
                from django.contrib.auth import login as auth_login
                auth_login(request, user)
                base = (getattr(settings, "SITE_URL", "") or "").rstrip("/") or request.build_absolute_uri("/").rstrip("/")
                return Response(
                    {
                        "success": True,
                        "message": "Registration successful. Your 12-day free trial has started.",
                        "admin_id": admin.id,
                        "trial_ends_at": trial_ends_at.isoformat(),
                        "panel_url": f"{base}/panel/?admin_id={admin.id}",
                    },
                    status=status.HTTP_201_CREATED,
                )
            except IntegrityError as e:
                err_str = str(e).lower()
                is_pkey_duplicate = (
                    "auth_user_pkey" in err_str
                    or "duplicate key" in err_str
                    or "business_menu_businessadmin_pkey" in err_str
                    or "business_menu_restaurant_pkey" in err_str
                )
                if is_pkey_duplicate and attempt == 0:
                    logger.warning("Signup sequence conflict, fixing sequences and retrying: %s", e)
                    continue
                logger.exception("Restaurant owner signup failed: %s", e)
                return Response(
                    {"success": False, "message": "Registration failed (duplicate or database error). Please try again or contact support."},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )
            except Exception as e:
                logger.exception("Restaurant owner signup failed: %s", e)
                return Response(
                    {"success": False, "message": str(e)},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )
        return Response(
            {"success": False, "message": "Registration failed (duplicate or database error). Please try again or contact support."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


class PaymentPageView(APIView):
    """
    View for payment page after successful registration
    GET /business-menu/payment/?admin_id=123 - Display payment page with QR code
    """
    permission_classes = [permissions.AllowAny]
    
    def get(self, request):
        """Display payment page with QR code"""
        admin_id = request.GET.get('admin_id')
        context = {}
        if admin_id:
            try:
                admin = BusinessAdmin.objects.get(id=admin_id)
                context['admin'] = admin
                context['admin_id'] = admin_id
            except BusinessAdmin.DoesNotExist:
                pass
        return render(request, 'business_menu/payment.html', context)
