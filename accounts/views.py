from __future__ import annotations

from django.contrib.auth.models import User
from django.contrib.auth.hashers import make_password
from django.core.mail import send_mail, get_connection
from datetime import timedelta
import random
from django.db.models import Count, Q
import re
from django.utils import timezone
from django.shortcuts import render
from rest_framework import permissions, status, viewsets, serializers
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .models import Profile, UserActivity, Business, EmailVerificationCode, PasswordResetCode
try:
    from loyalty.models import Business as LoyaltyBusiness
except ImportError:
    LoyaltyBusiness = None
try:
    from notifications.models import Device
except ImportError:
    Device = None
from django.conf import settings
from django.db import transaction
from .serializers import (
    ProfileSerializer, RegisterSerializer, UserSerializer, UserActivitySerializer, 
    BusinessSerializer, SendOTPSerializer, CheckOTPSerializer, RegisterWithOTPSerializer
)
from .permissions import IsSuperUserRole, IsAdminRole, CanManageUsers, IsOwnerOrSuperUser
from .twilio_utils import (
    send_otp,
    check_otp,
    format_phone_number,
    phone_variants_for_lookup,
    UNLIMITED_OTP_PHONES,
)
from .email_utils import send_email_verification_code, verify_email_code
from .throttling import LoginThrottle, RegisterThrottle, OTPThrottle, PasswordResetThrottle


class LoginView(APIView):
    """
    Login endpoint - authenticates user with phone number and password
    Returns JWT tokens on success
    SECURITY: Rate limited to prevent brute force attacks
    """
    permission_classes = [permissions.AllowAny]
    throttle_classes = [LoginThrottle]

    def get(self, request):
        """If browser (Accept: text/html), redirect to HTML login page."""
        accept = request.META.get("HTTP_ACCEPT", "")
        if "text/html" in accept:
            from django.shortcuts import redirect
            return redirect("/auth/login/")
        return Response(
            {"detail": "POST to login. Send phone/number and password.", "allowed_methods": ["POST", "OPTIONS"]},
            status=status.HTTP_200_OK,
        )

    def post(self, request):
        # Accept both 'phone' and 'number' for backward compatibility
        number = request.data.get('number', '').strip() or request.data.get('phone', '').strip()
        password = request.data.get('password', '')
        
        if not number or not password:
            return Response({
                'error': 'Phone number and password are required',
                'detail': 'Please provide both phone number and password (use "phone" or "number" field)'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Normalize phone number - remove all non-digit characters except +
        def normalize_phone(phone_str):
            """Remove all non-digit characters except +"""
            if not phone_str:
                return ''
            return ''.join(c for c in phone_str if c.isdigit() or c == '+')
        
        # Generate all possible phone number variants
        phone_variants = set()
        
        # Original number (normalized)
        normalized = normalize_phone(number)
        if normalized:
            phone_variants.add(normalized)
            phone_variants.add(number.strip())  # Also try original as-is
        
        # Try formatted version (E.164 format)
        try:
            formatted = format_phone_number(number)
            phone_variants.add(formatted)
            phone_variants.add(normalize_phone(formatted))
        except Exception:
            pass
        
        # Try without leading zero
        if normalized.startswith('0'):
            without_zero = normalized[1:]
            phone_variants.add(without_zero)
            # Also try with country code
            try:
                with_country = format_phone_number(without_zero)
                phone_variants.add(with_country)
                phone_variants.add(normalize_phone(with_country))
            except Exception:
                pass
        
        # Try with leading zero if doesn't have it
        if not normalized.startswith('0') and not normalized.startswith('+'):
            with_zero = '0' + normalized
            phone_variants.add(with_zero)
        
        # Try with +49 prefix (Germany)
        if not normalized.startswith('+'):
            if normalized.startswith('0'):
                # Remove 0 and add +49
                with_49 = '+49' + normalized[1:]
                phone_variants.add(with_49)
            else:
                # Add +49 directly
                with_49 = '+49' + normalized
                phone_variants.add(with_49)
        
        # Remove empty strings
        phone_variants = {v for v in phone_variants if v}
        
        # Debug: Log all variants being tried (only in DEBUG mode)
        if settings.DEBUG:
            import logging
            logger = logging.getLogger(__name__)
            logger.debug(f"Login attempt for number: {number}, trying variants: {phone_variants}")
        
        # Find user by phone number using Q objects to try all variants at once
        # This is more efficient than multiple get() calls
        if phone_variants:
            # Build Q object for all variants
            q_objects = Q()
            for variant in phone_variants:
                q_objects |= Q(phone=variant) | Q(phone__iexact=variant)
            
            # Also try with normalized versions (remove all non-digits)
            for variant in list(phone_variants):
                digits_only = re.sub(r'[^\d+]', '', variant)
                if digits_only and digits_only != variant:
                    q_objects |= Q(phone=digits_only) | Q(phone__iexact=digits_only)
            
            try:
                profile = Profile.objects.filter(q_objects).first()
            except Exception:
                profile = None
            
            # If still not found, try searching by normalizing database phone numbers
            # This handles cases where phone numbers in DB have spaces, dashes, etc.
            if not profile:
                try:
                    # Get all profiles and check normalized phone numbers
                    all_profiles = Profile.objects.exclude(phone='').exclude(phone__isnull=True)
                    for p in all_profiles:
                        db_phone_normalized = normalize_phone(p.phone)
                        for variant in phone_variants:
                            variant_normalized = normalize_phone(variant)
                            if db_phone_normalized and variant_normalized:
                                # Compare normalized versions (exact match)
                                if db_phone_normalized == variant_normalized:
                                    profile = p
                                    break
                                # Also try without + prefix
                                db_no_plus = db_phone_normalized.lstrip('+')
                                variant_no_plus = variant_normalized.lstrip('+')
                                if db_no_plus and variant_no_plus and db_no_plus == variant_no_plus:
                                    profile = p
                                    break
                                # Try matching last 10 digits (for cases like +49 30 vs 030)
                                if len(db_no_plus) >= 10 and len(variant_no_plus) >= 10:
                                    if db_no_plus[-10:] == variant_no_plus[-10:]:
                                        profile = p
                                        break
                        if profile:
                            break
                except Exception as e:
                    if settings.DEBUG:
                        import logging
                        logger = logging.getLogger(__name__)
                        logger.error(f"Error in phone search fallback: {e}")
                    pass
        else:
            profile = None
        
        # If not found in Profile, try searching in BusinessAdmin (for loyalty business admins)
        if not profile:
            try:
                from loyalty.models import BusinessAdmin as LoyaltyBusinessAdmin
                # Search in BusinessAdmin phone numbers
                for variant in phone_variants:
                    variant_normalized = normalize_phone(variant)
                    # Try exact match
                    business_admin = LoyaltyBusinessAdmin.objects.filter(phone=variant, is_active=True).first()
                    if business_admin and business_admin.user:
                        # Get the user's profile
                        profile = getattr(business_admin.user, 'profile', None)
                        if profile:
                            break
                    
                    # Try normalized match
                    all_business_admins = LoyaltyBusinessAdmin.objects.filter(is_active=True).exclude(phone='').exclude(phone__isnull=True)
                    for ba in all_business_admins:
                        if not ba.user:
                            continue
                        db_phone_normalized = normalize_phone(ba.phone)
                        if db_phone_normalized and variant_normalized:
                            if db_phone_normalized == variant_normalized:
                                profile = getattr(ba.user, 'profile', None)
                                if profile:
                                    break
                            # Try without + prefix
                            db_no_plus = db_phone_normalized.lstrip('+')
                            variant_no_plus = variant_normalized.lstrip('+')
                            if db_no_plus and variant_no_plus and db_no_plus == variant_no_plus:
                                profile = getattr(ba.user, 'profile', None)
                                if profile:
                                    break
                            # Try matching last 10 digits
                            if len(db_no_plus) >= 10 and len(variant_no_plus) >= 10:
                                if db_no_plus[-10:] == variant_no_plus[-10:]:
                                    profile = getattr(ba.user, 'profile', None)
                                    if profile:
                                        break
                        if profile:
                            break
                    if profile:
                        break
            except Exception as e:
                if settings.DEBUG:
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.error(f"Error searching BusinessAdmin phone: {e}")
                pass
        
        # If not found in BusinessAdmin, try searching in Business phone (for business admins) – only if loyalty is installed
        if not profile and LoyaltyBusiness is not None:
            try:
                # Search in Business phone numbers - get business admin's profile
                for variant in phone_variants:
                    variant_normalized = normalize_phone(variant)
                    # Try exact match
                    business = LoyaltyBusiness.objects.filter(phone=variant).first()
                    if business and business.business_admin and business.business_admin.user:
                        # Get the business admin's profile
                        profile = getattr(business.business_admin.user, 'profile', None)
                        if profile:
                            break
                    
                    # Try normalized match
                    all_businesses = LoyaltyBusiness.objects.exclude(phone='').exclude(phone__isnull=True).select_related('business_admin__user')
                    for b in all_businesses:
                        if not b.business_admin or not b.business_admin.user:
                            continue
                        db_phone_normalized = normalize_phone(b.phone)
                        if db_phone_normalized and variant_normalized:
                            if db_phone_normalized == variant_normalized:
                                profile = getattr(b.business_admin.user, 'profile', None)
                                if profile:
                                    break
                            # Try without + prefix
                            db_no_plus = db_phone_normalized.lstrip('+')
                            variant_no_plus = variant_normalized.lstrip('+')
                            if db_no_plus and variant_no_plus and db_no_plus == variant_no_plus:
                                profile = getattr(b.business_admin.user, 'profile', None)
                                if profile:
                                    break
                            # Try matching last 10 digits
                            if len(db_no_plus) >= 10 and len(variant_no_plus) >= 10:
                                if db_no_plus[-10:] == variant_no_plus[-10:]:
                                    profile = getattr(b.business_admin.user, 'profile', None)
                                    if profile:
                                        break
                        if profile:
                            break
                    if profile:
                        break
            except Exception as e:
                if settings.DEBUG:
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.error(f"Error searching Business phone: {e}")
                pass
        
        if not profile:
            return Response({
                'error': 'Phone number not found',
                'detail': 'No account found with this phone number. Please check your phone number or register a new account.'
            }, status=status.HTTP_404_NOT_FOUND)
        
        try:
            user = profile.user
            
            # Check password
            if not user.check_password(password):
                try:
                    import logging
                    logging.getLogger(__name__).info(
                        "Login password mismatch: user_id=%s phone=%s password_len=%s",
                        getattr(user, "id", None),
                        number,
                        len(password) if password is not None else None,
                    )
                except Exception:
                    pass
                return Response({
                    'error': 'Invalid password',
                    'detail': 'The password you entered is incorrect. Please check your password and try again.'
                }, status=status.HTTP_401_UNAUTHORIZED)
            
            # Check if user is active
            if not user.is_active or not profile.is_active:
                return Response({
                    'error': 'Account disabled',
                    'detail': 'Your account has been disabled'
                }, status=status.HTTP_403_FORBIDDEN)
            
            # Update activity
            profile.update_activity(ip_address=self.get_client_ip(request))
            
            # Log login activity
            try:
                UserActivity.objects.create(
                    user=user,
                    activity_type=UserActivity.ActivityType.LOGIN,
                    description="User logged in successfully",
                    ip_address=self.get_client_ip(request),
                    user_agent=request.META.get('HTTP_USER_AGENT', '')
                )
            except Exception:
                pass
            
            # Generate JWT tokens
            refresh = RefreshToken.for_user(user)
            
            return Response({
                'access': str(refresh.access_token),
                'refresh': str(refresh),
                'user': UserSerializer(user).data,
                'profile': ProfileSerializer(profile).data,
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            # Handle any other errors
            return Response({
                'error': 'Login failed',
                'detail': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def get_client_ip(self, request):
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip


class RegisterView(APIView):
    """
    Register endpoint - creates new user with phone number, password, and interests
    Returns JWT tokens on success.
    If phone already exists: logs user in and returns tokens (200) so app goes straight in.
    SECURITY: Rate limited to prevent abuse
    """
    permission_classes = [permissions.AllowAny]
    throttle_classes = [RegisterThrottle]

    def get(self, request):
        """If browser (Accept: text/html), redirect to HTML register page. Else return API info."""
        accept = request.META.get("HTTP_ACCEPT", "")
        if "text/html" in accept:
            from django.shortcuts import redirect
            return redirect("/auth/register/")
        return Response(
            {
                "detail": "POST to register. Send phone/number, password, interests. Returns JWT on success.",
                "allowed_methods": ["POST", "OPTIONS"],
            },
            status=status.HTTP_200_OK,
        )

    def post(self, request):
        # If this phone is already registered, log them in and return tokens (no 409)
        number = (request.data.get('number') or request.data.get('phone') or '').strip()
        if number:
            try:
                # Robust lookup (supports +90..., 05..., spaces/dashes)
                try:
                    formatted = format_phone_number(number)
                except Exception:
                    formatted = number

                variants = phone_variants_for_lookup(formatted)
                profile = Profile.objects.filter(phone__in=variants).first() if variants else None

                # Fallback: match digit sequence even if DB stored spaces/dashes (e.g. '+90 554 022 5177')
                if not profile:
                    try:
                        from .twilio_utils import phone_digits_sequence_regex
                        digits = re.sub(r"\D", "", formatted or "")
                        pattern = phone_digits_sequence_regex(digits[-10:]) if len(digits) >= 10 else ""
                        if pattern:
                            profile = Profile.objects.filter(phone__regex=pattern).first()
                    except Exception:
                        profile = None

                if not profile and formatted:
                    profile = Profile.objects.filter(phone__iexact=formatted).first()

                if profile:
                    # Canonicalize stored phone to keep future lookups consistent
                    try:
                        if formatted and (profile.phone or "") != formatted:
                            profile.phone = formatted
                            profile.save(update_fields=["phone"])
                    except Exception:
                        pass
                    user = profile.user
                    # Ensure loyalty.Customer exists and has phone
                    try:
                        from loyalty.models import Customer as LoyaltyCustomer
                        customer, _ = LoyaltyCustomer.objects.get_or_create(user=user)
                        phone_value = profile.phone or formatted
                        if phone_value and (customer.phone or "") != phone_value:
                            customer.phone = phone_value
                            customer.save(update_fields=["phone"])
                    except Exception:
                        pass
                    refresh = RefreshToken.for_user(user)
                    return Response({
                        "access": str(refresh.access_token),
                        "refresh": str(refresh),
                        "user": UserSerializer(user).data,
                        "profile": ProfileSerializer(profile).data,
                        "already_registered": True,
                        "message": "You are already registered. Logged in successfully.",
                    }, status=status.HTTP_200_OK)
            except Exception:
                pass

        # Normalize input keys for backward compatibility with mobile clients
        data = request.data.copy() if hasattr(request.data, "copy") else dict(request.data)
        if not (data.get("number") or "").strip():
            phone_alias = (data.get("phone") or data.get("number") or "").strip()
            if phone_alias:
                data["number"] = phone_alias
        if not (data.get("confirmPassword") or "").strip():
            alt = (data.get("confirm_password") or data.get("confirm") or "").strip()
            if alt:
                data["confirmPassword"] = alt
        # Interests/favorites field alias
        if data.get("favorit") is None:
            if data.get("favorites") is not None:
                data["favorit"] = data.get("favorites")
            elif data.get("interests") is not None:
                data["favorit"] = data.get("interests")

        try:
            serializer = RegisterSerializer(data=data)
            serializer.is_valid(raise_exception=True)
            user = serializer.save()
            
            # Ensure profile exists (should be created by signal, but just in case)
            profile, _ = Profile.objects.get_or_create(user=user)
            
            # Log user registration activity
            try:
                UserActivity.objects.create(
                    user=user,
                    activity_type=UserActivity.ActivityType.LOGIN,
                    description="User registered successfully",
                    ip_address=self.get_client_ip(request),
                    user_agent=request.META.get('HTTP_USER_AGENT', '')
                )
            except Exception as e:
                # Log activity creation failure but don't fail registration
                pass
            
            # Generate JWT tokens for the newly registered user
            refresh = RefreshToken.for_user(user)
            
            return Response({
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "user": UserSerializer(user).data,
                "profile": ProfileSerializer(profile).data,
            }, status=status.HTTP_200_OK)
        except serializers.ValidationError as e:
            # If "phone already exists" - return structured response so app can redirect to OTP login
            detail = e.detail if hasattr(e, 'detail') else {}
            if isinstance(detail, dict) and detail.get('number'):
                number_raw = (data.get('number') or data.get('phone') or '').strip()
                try:
                    from .twilio_utils import format_phone_number
                    phone_canonical = format_phone_number(number_raw)
                except Exception:
                    phone_canonical = number_raw
                return Response({
                    "error": detail,
                    "detail": "A user with this phone number already exists. Please log in with OTP.",
                    "already_registered": True,
                    "message": "A user with this phone number already exists. Please log in with OTP.",
                    "phone": phone_canonical,
                }, status=status.HTTP_409_CONFLICT)
            # Return specific error messages from serializer validation
            # Extract the first error message if it's a dict, or use the error directly
            if isinstance(detail, dict):
                # Get the first error message from any field
                first_error = None
                for field, errors in detail.items():
                    if errors:
                        if isinstance(errors, list) and len(errors) > 0:
                            first_error = errors[0]
                        elif isinstance(errors, str):
                            first_error = errors
                        break
                error_detail = first_error if first_error else "Please check your input data."
            elif isinstance(detail, list) and len(detail) > 0:
                error_detail = detail[0]
            elif isinstance(detail, str):
                error_detail = detail
            else:
                error_detail = "Please check your input data."
            
            return Response({
                "error": detail,
                "detail": error_detail
            }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            # Better error handling
            error_message = str(e)
            if hasattr(e, 'detail'):
                error_message = e.detail
            elif hasattr(e, 'get_full_details'):
                error_message = e.get_full_details()
            
            return Response({
                "error": error_message,
                "detail": error_message if error_message else "An error occurred during registration. Please try again."
            }, status=status.HTTP_400_BAD_REQUEST)
    
    def get_client_ip(self, request):
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip


class MeView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        profile = getattr(request.user, "profile", None)
        return Response({
            "user": UserSerializer(request.user).data,
            "profile": ProfileSerializer(profile).data if profile else None,
        })

    def patch(self, request):
        """
        Update current user's personal info.
        Accepts flat fields: first_name, last_name, email,
        and profile fields: business_name, business_type, business_address, business_phone, interests.
        """
        user = request.user
        profile = getattr(user, "profile", None)

        updated_user_fields = []
        updated_profile_fields = []

        first_name = (request.data.get("first_name") or "").strip()
        last_name = (request.data.get("last_name") or "").strip()
        email = (request.data.get("email") or "").strip()

        if first_name:
            user.first_name = first_name
            updated_user_fields.append("first_name")
        if last_name:
            user.last_name = last_name
            updated_user_fields.append("last_name")
        if email and email != (user.email or ""):
            # Ensure unique email
            from django.contrib.auth.models import User as DjangoUser
            if DjangoUser.objects.filter(email__iexact=email).exclude(id=user.id).exists():
                return Response({"detail": "This email is already registered."}, status=status.HTTP_400_BAD_REQUEST)
            user.email = email
            updated_user_fields.append("email")

        if updated_user_fields:
            user.save(update_fields=updated_user_fields)

        if profile:
            business_name = (request.data.get("business_name") or "").strip()
            business_type = (request.data.get("business_type") or "").strip()
            business_address = (request.data.get("business_address") or "").strip()
            business_phone = (request.data.get("business_phone") or "").strip()
            interests = request.data.get("interests", None)

            if business_name:
                profile.business_name = business_name
                updated_profile_fields.append("business_name")
            if business_type:
                profile.business_type = business_type
                updated_profile_fields.append("business_type")
            if business_address:
                profile.business_address = business_address
                updated_profile_fields.append("business_address")
            if business_phone:
                profile.business_phone = business_phone
                updated_profile_fields.append("business_phone")
            if interests is not None:
                if not isinstance(interests, list):
                    return Response({"detail": "interests must be a list"}, status=status.HTTP_400_BAD_REQUEST)
                profile.interests = interests
                updated_profile_fields.append("interests")

            if updated_profile_fields:
                profile.save(update_fields=updated_profile_fields)

        # Log activity (best-effort)
        if updated_user_fields or updated_profile_fields:
            try:
                UserActivity.objects.create(
                    user=user,
                    activity_type=UserActivity.ActivityType.PROFILE_UPDATE,
                    description="User updated profile information",
                    ip_address=request.META.get('REMOTE_ADDR'),
                    user_agent=request.META.get('HTTP_USER_AGENT', '')
                )
            except Exception:
                pass

        return Response({
            "user": UserSerializer(user).data,
            "profile": ProfileSerializer(profile).data if profile else None,
        }, status=status.HTTP_200_OK)


class SetRoleView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsSuperUserRole]

    def post(self, request, user_id: int):
        role = request.data.get("role")
        if role not in dict(Profile.Role.choices):
            return Response({"detail": "invalid role"}, status=status.HTTP_400_BAD_REQUEST)
        
        user = User.objects.filter(id=user_id).first()
        if not user:
            return Response({"detail": "user not found"}, status=status.HTTP_404_NOT_FOUND)
        
        profile, _ = Profile.objects.get_or_create(user=user)
        old_role = profile.role
        profile.role = role
        profile.save(update_fields=["role"])
        
        # Log role change activity
        UserActivity.objects.create(
            user=request.user,
            activity_type=UserActivity.ActivityType.PROFILE_UPDATE,
            description=f"Changed user {user.username} role from {old_role} to {role}",
            ip_address=self.get_client_ip(request),
            user_agent=request.META.get('HTTP_USER_AGENT', '')
        )
        
        return Response({"user": UserSerializer(user).data, "profile": ProfileSerializer(profile).data})
    
    def get_client_ip(self, request):
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip


class UserManagementViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing users - only accessible by superusers
    """
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated, IsSuperUserRole]
    
    def get_queryset(self):
        queryset = User.objects.select_related('profile').all()
        
        # Filter by role if specified
        role = self.request.query_params.get('role')
        if role:
            queryset = queryset.filter(profile__role=role)
        
        # Filter by active status
        is_active = self.request.query_params.get('is_active')
        if is_active is not None:
            queryset = queryset.filter(profile__is_active=is_active.lower() == 'true')
        
        return queryset.order_by('-date_joined')
    
    @action(detail=True, methods=['post'])
    def activate(self, request, pk=None):
        """Activate/deactivate a user"""
        user = self.get_object()
        profile = user.profile
        
        is_active = request.data.get('is_active', True)
        profile.is_active = is_active
        profile.save(update_fields=['is_active'])
        
        # Log activity
        UserActivity.objects.create(
            user=request.user,
            activity_type=UserActivity.ActivityType.PROFILE_UPDATE,
            description=f"{'Activated' if is_active else 'Deactivated'} user {user.username}",
            ip_address=self.get_client_ip(request),
            user_agent=request.META.get('HTTP_USER_AGENT', '')
        )
        
        return Response({
            'message': f"User {user.username} {'activated' if is_active else 'deactivated'} successfully",
            'user': UserSerializer(user).data,
            'profile': ProfileSerializer(profile).data
        })
    
    @action(detail=False, methods=['get'])
    def stats(self, request):
        """Get user statistics"""
        total_users = User.objects.count()
        active_users = User.objects.filter(profile__is_active=True).count()
        
        role_stats = User.objects.values('profile__role').annotate(
            count=Count('id')
        ).order_by('profile__role')
        
        recent_registrations = User.objects.filter(
            date_joined__gte=timezone.now() - timezone.timedelta(days=30)
        ).count()
        
        return Response({
            'total_users': total_users,
            'active_users': active_users,
            'inactive_users': total_users - active_users,
            'role_distribution': list(role_stats),
            'recent_registrations_30d': recent_registrations
        })
    
    def get_client_ip(self, request):
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip


class UserActivityViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for viewing user activities - only accessible by superusers
    """
    queryset = UserActivity.objects.all()
    serializer_class = UserActivitySerializer
    permission_classes = [permissions.IsAuthenticated, IsSuperUserRole]
    
    def get_queryset(self):
        queryset = UserActivity.objects.select_related('user').all()
        
        # Filter by user if specified
        user_id = self.request.query_params.get('user_id')
        if user_id:
            queryset = queryset.filter(user_id=user_id)
        
        # Filter by activity type if specified
        activity_type = self.request.query_params.get('activity_type')
        if activity_type:
            queryset = queryset.filter(activity_type=activity_type)
        
        # Filter by date range
        start_date = self.request.query_params.get('start_date')
        end_date = self.request.query_params.get('end_date')
        
        if start_date:
            queryset = queryset.filter(created_at__gte=start_date)
        if end_date:
            queryset = queryset.filter(created_at__lte=end_date)
        
        return queryset.order_by('-created_at')


class BusinessManagementViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing businesses - accessible by superusers and admins
    """
    queryset = Business.objects.all()
    serializer_class = BusinessSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdminRole]
    
    def get_queryset(self):
        queryset = Business.objects.select_related('owner').all()
        
        # Filter by business type if specified
        business_type = self.request.query_params.get('business_type')
        if business_type:
            queryset = queryset.filter(business_type=business_type)
        
        # Filter by active status
        is_active = self.request.query_params.get('is_active')
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active.lower() == 'true')
        
        return queryset.order_by('-created_at')
    
    @action(detail=False, methods=['get'])
    def stats(self, request):
        """Get business statistics"""
        total_businesses = Business.objects.count()
        active_businesses = Business.objects.filter(is_active=True).count()
        
        business_type_stats = Business.objects.values('business_type').annotate(
            count=Count('id')
        ).order_by('business_type')
        
        total_revenue = Business.objects.aggregate(
            total=models.Sum('total_revenue')
        )['total'] or 0
        
        return Response({
            'total_businesses': total_businesses,
            'active_businesses': active_businesses,
            'inactive_businesses': total_businesses - active_businesses,
            'business_type_distribution': list(business_type_stats),
            'total_revenue': float(total_revenue)
        })


class DashboardStatsView(APIView):
    """
    Dashboard statistics for superusers - cached for performance
    """
    permission_classes = [permissions.IsAuthenticated, IsSuperUserRole]
    
    def get(self, request):
        from django.db.models import Sum, Q, Count
        from django.core.cache import cache
        
        # Cache stats for 60 seconds
        cache_key = 'dashboard_stats_api'
        cached_stats = cache.get(cache_key)
        if cached_stats:
            return Response(cached_stats)
        
        # Optimize queries - use annotations to combine queries
        # User statistics - single query with annotation
        user_stats = User.objects.aggregate(
            total=Count('id'),
            active=Count('id', filter=Q(profile__is_active=True))
        )
        
        # Business statistics - single query
        business_stats = Business.objects.aggregate(
            total=Count('id'),
            active=Count('id', filter=Q(is_active=True)),
            total_revenue=Sum('total_revenue')
        )
        
        # Activity statistics
        seven_days_ago = timezone.now() - timezone.timedelta(days=7)
        recent_activities = UserActivity.objects.filter(
            created_at__gte=seven_days_ago
        ).count()
        
        # Recent registrations
        thirty_days_ago = timezone.now() - timezone.timedelta(days=30)
        recent_registrations = User.objects.filter(
            date_joined__gte=thirty_days_ago
        ).count()
        
        stats_data = {
            'users': {
                'total': user_stats['total'] or 0,
                'active': user_stats['active'] or 0,
                'recent_registrations_30d': recent_registrations
            },
            'businesses': {
                'total': business_stats['total'] or 0,
                'active': business_stats['active'] or 0
            },
            'activities': {
                'recent_7d': recent_activities
            },
            'revenue': {
                'total': float(business_stats['total_revenue'] or 0)
            }
        }
        
        # Cache for 60 seconds
        cache.set(cache_key, stats_data, 60)
        
        return Response(stats_data)


class SendMobileView(APIView):
    """
    Send mobile endpoint - checks if phone number exists
    POST /api/accounts/sendMobile/
    Body: {"number": "09123456789"}
    
    Returns:
    - 200: User exists (go to login)
    - 201: User doesn't exist (go to register)
    - 400: Missing phone number
    """
    permission_classes = [permissions.AllowAny]
    
    def post(self, request):
        number = request.data.get('number', '').strip()
        
        if not number:
            return Response({
                'error': 'Phone number is required',
                'detail': 'Please provide a phone number'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Normalize phone and check if user exists (so +90..., 055..., 55... match)
        try:
            formatted = format_phone_number(number)
        except Exception:
            formatted = number

        variants = phone_variants_for_lookup(formatted)
        profile = Profile.objects.filter(phone__in=variants).first() if variants else None

        # Fallback: match digit sequence even if DB stored spaces/dashes (e.g. '+90 554 022 5177')
        if not profile:
            try:
                from .twilio_utils import phone_digits_sequence_regex
                digits = re.sub(r"\\D", "", formatted or "")
                pattern = phone_digits_sequence_regex(digits[-10:]) if len(digits) >= 10 else ""
                if pattern:
                    profile = Profile.objects.filter(phone__regex=pattern).first()
            except Exception:
                profile = None

        if profile:
            # Canonicalize stored phone to keep future lookups consistent
            try:
                if (profile.phone or "") != formatted:
                    profile.phone = formatted
                    profile.save(update_fields=["phone"])
            except Exception:
                pass
            return Response({
                'message': 'User found',
                'exists': True,
                'phone': formatted
            }, status=status.HTTP_200_OK)

        return Response({
            'message': 'User not found',
            'exists': False,
            'phone': formatted
        }, status=status.HTTP_201_CREATED)


class VerifyEmailView(APIView):
    """
    Verify email endpoint - verifies email verification code
    POST /api/accounts/verify-email/
    Body: {"user_id": 1, "code": "123456"}
    
    Returns:
    - 200: Email verified successfully
    - 400: Invalid code or expired
    """
    permission_classes = [permissions.AllowAny]
    
    def post(self, request):
        user_id = request.data.get('user_id')
        code = request.data.get('code', '').strip()
        
        if not user_id or not code:
            return Response({
                'error': 'User ID and verification code are required',
                'detail': 'Please provide both user_id and code'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response({
                'error': 'User not found',
                'detail': 'Invalid user ID'
            }, status=status.HTTP_404_NOT_FOUND)
        
        # Find the most recent verification code for this user
        try:
            verification = EmailVerificationCode.objects.filter(
                user=user,
                code=code,
                is_verified=False
            ).order_by('-created_at').first()
            
            if not verification:
                return Response({
                    'error': 'Invalid verification code',
                    'detail': 'The verification code is incorrect or already used'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Check if code is expired
            if verification.is_expired():
                return Response({
                    'error': 'Verification code expired',
                    'detail': 'The verification code has expired. Please request a new one.'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Verify the code
            verification.is_verified = True
            verification.save()
            
            # Ensure email is unique before assigning
            if User.objects.filter(email__iexact=verification.email).exclude(id=user.id).exists():
                return Response({
                    'error': 'Email already registered',
                    'detail': 'This email is already registered.'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Update user email
            user.email = verification.email.strip().lower()
            user.save(update_fields=['email'])
            
            return Response({
                'message': 'Email verified successfully',
                'email': verification.email,
                'user': UserSerializer(user).data
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            return Response({
                'error': 'Verification failed',
                'detail': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class SendEmailCodeView(APIView):
    """
    Send an email verification code to the provided email for a user.
    POST /api/accounts/send-email-code/
    Body: {"email": "user@example.com", "user_id": 1 (optional)}
    Priority for selecting user:
      - user_id (if provided)
      - authenticated user (if logged in)
      - user found by email (if unique)
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        email = (request.data.get("email") or "").strip()
        user_id = request.data.get("user_id")
        username = (request.data.get("username") or "").strip()
        number = (request.data.get("number") or "").strip()  # phone number (for mobile app)

        if not email:
            return Response({"detail": "email is required"}, status=status.HTTP_400_BAD_REQUEST)

        user = None
        if user_id:
            user = User.objects.filter(id=user_id).first()
            if not user:
                return Response({"detail": "user not found"}, status=status.HTTP_404_NOT_FOUND)
        elif request.user and request.user.is_authenticated:
            user = request.user
        elif username:
            user = User.objects.filter(username__iexact=username).first()
        elif number:
            # Resolve by phone number via Profile
            try:
                profile = Profile.objects.get(phone=number)
                user = profile.user
            except Profile.DoesNotExist:
                user = None
        else:
            # Try to find user by email (only if unique)
            qs = User.objects.filter(email__iexact=email)
            if qs.count() == 1:
                user = qs.first()

        if not user:
            return Response({"detail": "unable to resolve user for this email"}, status=status.HTTP_400_BAD_REQUEST)

        # Reject if this email is already registered to another user
        if User.objects.filter(email__iexact=email).exclude(id=user.id).exists():
            return Response({"detail": "This email is already registered."}, status=status.HTTP_400_BAD_REQUEST)

        code = str(random.randint(100000, 999999))
        expires_at = timezone.now() + timedelta(minutes=10)
        EmailVerificationCode.objects.create(user=user, email=email, code=code, expires_at=expires_at)

        try:
            bonus_connection = get_connection(
                backend="django.core.mail.backends.smtp.EmailBackend",
                host=getattr(settings, "BONUS_EMAIL_HOST", settings.EMAIL_HOST),
                port=getattr(settings, "BONUS_EMAIL_PORT", settings.EMAIL_PORT),
                username=getattr(settings, "BONUS_EMAIL_HOST_USER", settings.EMAIL_HOST_USER),
                password=getattr(settings, "BONUS_EMAIL_HOST_PASSWORD", settings.EMAIL_HOST_PASSWORD),
                use_tls=getattr(settings, "BONUS_EMAIL_USE_TLS", getattr(settings, "EMAIL_USE_TLS", True)),
                timeout=30,
            )
            send_mail(
                subject="Email Verification Code",
                message=f"Your verification code is: {code}\n\nThis code will expire in 10 minutes.",
                from_email=getattr(settings, "BONUS_FROM_EMAIL", None),
                recipient_list=[email],
                fail_silently=False,
                connection=bonus_connection,
            )
            return Response({"message": "verification code sent"}, status=status.HTTP_200_OK)
        except Exception as e:
            # In development, return the code to allow testing
            if settings.DEBUG:
                return Response({"message": "verification code generated (DEBUG)", "code": code}, status=status.HTTP_200_OK)
            return Response({"detail": "failed to send email"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class PasswordForgotView(APIView):
    """
    Start password reset by sending a 6-digit code to user's email.
    POST /api/accounts/password/forgot/
    Body: {"email": "user@example.com", "number": "09...", "username": "...", "user_id": 1}

    Always returns 200 to avoid email enumeration.
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        email = (request.data.get("email") or "").strip().lower()
        username = (request.data.get("username") or "").strip()
        number = (request.data.get("number") or "").strip()
        user_id = request.data.get("user_id")

        if not email:
            return Response({"detail": "email is required"}, status=status.HTTP_400_BAD_REQUEST)

        # Prefer user by phone when number is sent (same user that will be used at login)
        user = None
        if number:
            try:
                formatted = format_phone_number(number)
                variants = phone_variants_for_lookup(formatted)
                profile = Profile.objects.filter(phone__in=variants).first() if variants else None
                if profile and (profile.user.email or "").strip().lower() == email:
                    user = profile.user
            except Exception:
                pass
        if not user:
            user = User.objects.filter(email__iexact=email).first()
        if not user and request.user and request.user.is_authenticated:
            user = request.user
        if not user and number:
            try:
                profile = Profile.objects.get(phone=number)
                user = profile.user
            except Profile.DoesNotExist:
                user = None
        if not user and username:
            user = User.objects.filter(username__iexact=username).first()
        if not user and user_id:
            user = User.objects.filter(id=user_id).first()

        # Only allow OTP if user exists AND the email entered matches the user's registered email
        if not user:
            return Response(
                {"detail": "این ایمیل ثبت نشده است.", "error": "email_not_registered"},
                status=status.HTTP_400_BAD_REQUEST
            )
        registered_email = (user.email or "").strip().lower()
        if registered_email != email:
            return Response(
                {"detail": "جیمیل درست نیست. ایمیل باید همان ایمیلی باشد که در ثبت‌نام استفاده شده.", "error": "email_mismatch"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Send reset code to registered email
        code = str(random.randint(100000, 999999))
        expires_at = timezone.now() + timedelta(minutes=10)
        PasswordResetCode.objects.create(user=user, email=email, code=code, expires_at=expires_at)
        try:
            bonus_connection = get_connection(
                backend="django.core.mail.backends.smtp.EmailBackend",
                host=getattr(settings, "BONUS_EMAIL_HOST", settings.EMAIL_HOST),
                port=getattr(settings, "BONUS_EMAIL_PORT", settings.EMAIL_PORT),
                username=getattr(settings, "BONUS_EMAIL_HOST_USER", settings.EMAIL_HOST_USER),
                password=getattr(settings, "BONUS_EMAIL_HOST_PASSWORD", settings.EMAIL_HOST_PASSWORD),
                use_tls=getattr(settings, "BONUS_EMAIL_USE_TLS", getattr(settings, "EMAIL_USE_TLS", True)),
                timeout=30,
            )
            send_mail(
                subject="Password Reset Code",
                message=f"Your password reset code is: {code}\n\nThis code will expire in 10 minutes.",
                from_email=getattr(settings, "BONUS_FROM_EMAIL", None),
                recipient_list=[email],
                fail_silently=False,
                connection=bonus_connection,
            )
        except Exception:
            if settings.DEBUG:
                return Response({"message": "verification code generated (DEBUG)", "code": code}, status=status.HTTP_200_OK)
            pass

        return Response({"message": "کد بازیابی به ایمیل شما ارسال شد."}, status=status.HTTP_200_OK)


class PasswordVerifyView(APIView):
    """
    Verify password reset code (email + code).
    POST /api/accounts/password/verify/
    Body: {"email": "user@example.com", "code": "123456"}
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        email = (request.data.get("email") or "").strip().lower()
        code = (request.data.get("code") or "").strip()
        if not email or not code:
            return Response({"detail": "email and code are required"}, status=status.HTTP_400_BAD_REQUEST)

        reset = PasswordResetCode.objects.filter(
            email__iexact=email,
            code=code,
            is_used=False,
        ).order_by("-created_at").first()

        if not reset:
            return Response({"detail": "invalid code"}, status=status.HTTP_400_BAD_REQUEST)
        if reset.is_expired():
            return Response({"detail": "code expired"}, status=status.HTTP_400_BAD_REQUEST)

        return Response({"valid": True}, status=status.HTTP_200_OK)


class PasswordResetView(APIView):
    """
    SECURITY: Rate limited to prevent abuse
    """
    throttle_classes = [PasswordResetThrottle]
    """
    Reset password with email + code + new_password.
    POST /api/accounts/password/reset/
    Body: {"email":"user@example.com","code":"123456","new_password":"...","confirm_password":"..."}
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        email = (request.data.get("email") or "").strip().lower()
        code = (request.data.get("code") or "").strip()
        number = (request.data.get("number") or request.data.get("phone") or "").strip()
        # Accept both snake_case and camelCase (for mobile app)
        # IMPORTANT: do NOT strip passwords (spaces may be valid and stripping breaks login)
        new_password = (request.data.get("new_password") or request.data.get("newPassword") or "")
        confirm_password = (request.data.get("confirm_password") or request.data.get("confirmPassword") or "")

        if not email or not code or not new_password or not confirm_password:
            return Response({"detail": "email, code, new_password, confirm_password are required"}, status=status.HTTP_400_BAD_REQUEST)
        if new_password != confirm_password:
            return Response({"detail": "passwords do not match"}, status=status.HTTP_400_BAD_REQUEST)

        # If phone is sent, resolve user by phone (same as login) so we update the account that will log in
        user_by_phone = None
        if number:
            try:
                formatted = format_phone_number(number)
                variants = phone_variants_for_lookup(formatted)
                profile = Profile.objects.filter(phone__in=variants).first() if variants else None
                if profile and (profile.user.email or "").strip().lower() == email:
                    user_by_phone = profile.user
            except Exception:
                pass

        # Find reset: prefer the one for user_by_phone if we resolved by phone
        if user_by_phone:
            reset = PasswordResetCode.objects.filter(
                user=user_by_phone,
                email__iexact=email,
                code=code,
                is_used=False,
            ).order_by("-created_at").first()
        else:
            reset = PasswordResetCode.objects.filter(
                email__iexact=email,
                code=code,
                is_used=False,
            ).order_by("-created_at").first()

        if not reset:
            return Response({"detail": "invalid code or email"}, status=status.HTTP_400_BAD_REQUEST)
        if reset.is_expired():
            return Response({"detail": "code expired"}, status=status.HTTP_400_BAD_REQUEST)

        user = reset.user

        # Update password with direct DB update so it always persists (avoids worker/replica issues)
        hashed = make_password(new_password)
        # Update all users that have this email (Django default User.email is not unique in DB)
        # This prevents "reset succeeded but login fails" when duplicates exist historically.
        updated = User.objects.filter(email__iexact=email).update(password=hashed)
        if not updated:
            return Response({"detail": "Failed to update password."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # Verify (best-effort): ensure the target user's password matches what was provided.
        try:
            refreshed = User.objects.get(pk=user.pk)
            if not refreshed.check_password(new_password):
                return Response({"detail": "Password update failed. Please try again."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except Exception:
            pass

        # Mark codes as used (for this email) so they cannot be replayed
        PasswordResetCode.objects.filter(email__iexact=email, is_used=False).update(is_used=True)

        # Log activity (best-effort)
        try:
            UserActivity.objects.create(
                user=user,
                activity_type=UserActivity.ActivityType.PROFILE_UPDATE,
                description="User reset password via email code",
                ip_address=request.META.get('REMOTE_ADDR'),
                user_agent=request.META.get('HTTP_USER_AGENT', '')
            )
        except Exception:
            pass

        # Return updated count for easier debugging (safe additive field)
        return Response({"message": "password reset successful", "updated_users": updated}, status=status.HTTP_200_OK)


class PasswordChangeView(APIView):
    """
    Change password for authenticated users.
    POST /api/accounts/password/change/
    Body: {"old_password": "...", "new_password": "...", "confirm_password": "..."}
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        old_password = request.data.get("old_password") or ""
        new_password = request.data.get("new_password") or ""
        confirm_password = request.data.get("confirm_password") or ""

        if not old_password or not new_password or not confirm_password:
            return Response(
                {"detail": "old_password, new_password, and confirm_password are required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        if new_password != confirm_password:
            return Response(
                {"detail": "new_password and confirm_password do not match"},
                status=status.HTTP_400_BAD_REQUEST
            )

        user = request.user
        if not user.check_password(old_password):
            return Response(
                {"detail": "old_password is incorrect"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Update password
        user.set_password(new_password)
        user.save(update_fields=["password"])

        # Log activity (best-effort)
        try:
            UserActivity.objects.create(
                user=user,
                activity_type=UserActivity.ActivityType.PROFILE_UPDATE,
                description="User changed password",
                ip_address=request.META.get('REMOTE_ADDR'),
                user_agent=request.META.get('HTTP_USER_AGENT', '')
            )
        except Exception:
            pass

        return Response({"message": "password changed successfully"}, status=status.HTTP_200_OK)


class CustomTokenObtainPairView(TokenObtainPairView):
    """
    Custom TokenObtainPairView that accepts 'number' instead of 'username'
    POST /api/accounts/token/
    Body: {"number": "09123456789", "password": "password"}
    """
    def post(self, request, *args, **kwargs):
        # Get number from request
        number = request.data.get('number', '').strip()
        password = request.data.get('password', '')
        
        if not number or not password:
            return Response({
                'error': 'Phone number and password are required',
                'detail': 'Please provide both phone number and password'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Normalize phone number - same logic as LoginView
        def normalize_phone(phone_str):
            """Remove all non-digit characters except +"""
            if not phone_str:
                return ''
            return ''.join(c for c in phone_str if c.isdigit() or c == '+')
        
        # Generate all possible phone number variants
        phone_variants = set()
        normalized = normalize_phone(number)
        if normalized:
            phone_variants.add(normalized)
            phone_variants.add(number.strip())
        
        # Try formatted version
        try:
            formatted = format_phone_number(number)
            phone_variants.add(formatted)
            phone_variants.add(normalize_phone(formatted))
        except Exception:
            pass
        
        # Try without leading zero
        if normalized.startswith('0'):
            without_zero = normalized[1:]
            phone_variants.add(without_zero)
            try:
                with_country = format_phone_number(without_zero)
                phone_variants.add(with_country)
                phone_variants.add(normalize_phone(with_country))
            except Exception:
                pass
        
        # Try with leading zero if doesn't have it
        if not normalized.startswith('0') and not normalized.startswith('+'):
            with_zero = '0' + normalized
            phone_variants.add(with_zero)
        
        # Try with +49 prefix (Germany)
        if not normalized.startswith('+'):
            if normalized.startswith('0'):
                with_49 = '+49' + normalized[1:]
                phone_variants.add(with_49)
            else:
                with_49 = '+49' + normalized
                phone_variants.add(with_49)
        
        phone_variants = {v for v in phone_variants if v}
        
        # Find user by phone number
        if phone_variants:
            q_objects = Q()
            for variant in phone_variants:
                q_objects |= Q(phone=variant) | Q(phone__iexact=variant)
            
            for variant in list(phone_variants):
                digits_only = re.sub(r'[^\d+]', '', variant)
                if digits_only and digits_only != variant:
                    q_objects |= Q(phone=digits_only) | Q(phone__iexact=digits_only)
            
            try:
                profile = Profile.objects.filter(q_objects).first()
            except Exception:
                profile = None
            
            if profile:
                user = profile.user
                # Check password
                if user.check_password(password):
                    # Check if user is active
                    if not user.is_active or not profile.is_active:
                        return Response({
                            'error': 'Account disabled',
                            'detail': 'Your account has been disabled'
                        }, status=status.HTTP_403_FORBIDDEN)
                    
                    # Update activity
                    profile.update_activity(ip_address=self.get_client_ip(request))
                    
                    # Generate JWT tokens using parent class
                    # Temporarily set username in request.data for parent class
                    original_username = request.data.get('username')
                    request.data['username'] = user.username
                    
                    try:
                        response = super().post(request, *args, **kwargs)
                        return response
                    finally:
                        # Restore original username
                        if original_username is not None:
                            request.data['username'] = original_username
                        else:
                            request.data.pop('username', None)
        
        # If phone not found, try username as fallback
        # This allows users without phone to login with username
        try:
            user = User.objects.get(username=number)
            if user.check_password(password):
                profile = getattr(user, 'profile', None)
                if profile and not profile.is_active:
                    return Response({
                        'error': 'Account disabled',
                        'detail': 'Your account has been disabled'
                    }, status=status.HTTP_403_FORBIDDEN)
                
                if not user.is_active:
                    return Response({
                        'error': 'Account disabled',
                        'detail': 'Your account has been disabled'
                    }, status=status.HTTP_403_FORBIDDEN)
                
                # Update activity if profile exists
                if profile:
                    profile.update_activity(ip_address=self.get_client_ip(request))
                
                # Generate JWT tokens
                original_username = request.data.get('username')
                request.data['username'] = user.username
                
                try:
                    response = super().post(request, *args, **kwargs)
                    return response
                finally:
                    if original_username is not None:
                        request.data['username'] = original_username
                    else:
                        request.data.pop('username', None)
        except User.DoesNotExist:
            pass
        
        # If not found, return error
        return Response({
            'error': 'Phone number not found',
            'detail': 'No account found with this phone number. Please check your phone number or register a new account.'
        }, status=status.HTTP_404_NOT_FOUND)
    
    def get_client_ip(self, request):
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip


class LogoutView(APIView):
    """
    Logout endpoint - optional refresh token revoke and device token cleanup
    POST /api/accounts/logout/
    Headers: Authorization: Bearer <access>
    Body (optional):
      {
        "refresh": "<refresh_token>",  // optional, to revoke this session
        "all_sessions": false,         // optional, revoke all refresh tokens (if blacklist installed)
        "device_token": "<fcm token>", // optional, remove this device
        "all_devices": false           // optional, remove all user's devices
      }
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        tokens_revoked = False
        devices_removed = 0

        refresh_token_str = request.data.get("refresh") or request.data.get("refresh_token")
        all_sessions = bool(request.data.get("all_sessions"))
        device_token = (request.data.get("device_token") or request.data.get("fcmToken") or request.data.get("token") or "").strip()
        all_devices = bool(request.data.get("all_devices"))

        # Revoke refresh token(s) if possible
        try:
            # Try to import blacklist models dynamically
            from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken  # type: ignore
            if all_sessions:
                for outstanding in OutstandingToken.objects.filter(user=request.user):
                    BlacklistedToken.objects.get_or_create(token=outstanding)
                tokens_revoked = True
            elif refresh_token_str:
                try:
                    refresh_obj = RefreshToken(refresh_token_str)
                    # blacklist() raises if blacklist app is not installed; but we guarded import above
                    refresh_obj.blacklist()  # type: ignore[attr-defined]
                    tokens_revoked = True
                except Exception:
                    pass
        except Exception:
            # Blacklist app not installed or other error; ignore silently
            pass

        # Remove device tokens (only if notifications app is installed)
        try:
            if Device is not None:
                if all_devices:
                    devices_removed, _ = Device.objects.filter(user=request.user).delete()
                elif device_token:
                    devices_removed, _ = Device.objects.filter(user=request.user, token=device_token).delete()
        except Exception:
            pass

        # Log activity (best-effort)
        try:
            UserActivity.objects.create(
                user=request.user,
                activity_type=UserActivity.ActivityType.LOGOUT,
                description="User logged out",
                ip_address=request.META.get('REMOTE_ADDR'),
                user_agent=request.META.get('HTTP_USER_AGENT', '')
            )
        except Exception:
            pass

        return Response({
            "message": "logged out",
            "tokens_revoked": tokens_revoked,
            "devices_removed": devices_removed
        }, status=status.HTTP_200_OK)


class SendOTPView(APIView):
    """
    SECURITY: Rate limited to prevent abuse
    """
    throttle_classes = [OTPThrottle]
    """
    Send OTP code to phone number via Twilio SMS and email verification code
    POST /api/accounts/send-otp/
    Body: {"phone": "+491234567890"}
    
    Flow:
    1. Finds user by phone number
    2. If user exists and has email: sends OTP to phone AND email code to email
    3. If user doesn't exist or has no email: only sends OTP to phone
    
    Supports European phone numbers
    """
    permission_classes = [permissions.AllowAny]
    
    def post(self, request):
        serializer = SendOTPSerializer(data=request.data)
        
        if not serializer.is_valid():
            return Response({
                "success": False,
                "errors": serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)
        
        phone = serializer.validated_data['phone']
        
        # Format phone number to E.164 +49 (Germany only)
        try:
            formatted_phone = format_phone_number(phone)
        except Exception as e:
            digits = re.sub(r"\D", "", str(phone or ""))
            fallback_phone = f"+49{digits}" if digits else ""
            return Response({
                "success": False,
                "message": f"Invalid phone number format: {str(e)}",
                "phone": fallback_phone or "+49",
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Send OTP via Twilio (always send to phone)
        otp_result = send_otp(formatted_phone)
        
        # Check if user exists with this phone number
        email_result = None
        user_email = None
        profile = None
        try:
            variants = phone_variants_for_lookup(formatted_phone)
            profile = Profile.objects.filter(phone__in=variants).first() if variants else None
        except Exception:
            profile = None

        if profile:
            # Canonicalize stored phone to E.164 for consistent future logins
            try:
                if (profile.phone or "") != formatted_phone:
                    profile.phone = formatted_phone
                    profile.save(update_fields=["phone"])
            except Exception:
                pass

            user = profile.user
            user_email = user.email

            # If user has email, send email verification code
            if user_email:
                email_result = send_email_verification_code(user, user_email)
        
        # Prepare response
        response_data = {
            "success": otp_result['success'],
            "message": otp_result['message'],
            "status": otp_result.get('status', 'error'),
            "phone": formatted_phone,
            "otp_sent": otp_result['success']
        }
        
        # Add email info if available
        if user_email:
            response_data["email"] = user_email
            if email_result:
                response_data["email_code_sent"] = email_result['success']
                if email_result['success']:
                    response_data["message"] = f"{otp_result['message']} and verification code sent to your email"
                else:
                    response_data["email_error"] = email_result['message']
        
        if otp_result['success']:
            return Response(response_data, status=status.HTTP_200_OK)
        else:
            return Response({
                "success": False,
                "message": otp_result['message'],
                "status": otp_result.get('status', 'error'),
                "error_code": otp_result.get('error_code'),
                "phone": formatted_phone,
            }, status=status.HTTP_400_BAD_REQUEST)


class CheckOTPView(APIView):
    """
    SECURITY: Rate limited to prevent brute force attacks
    """
    throttle_classes = [OTPThrottle]
    """
    Verify OTP code entered by user (accepts both phone OTP and email code)
    POST /api/accounts/check-otp/
    Body: {"phone": "+491234567890", "code": "123456"}
    
    Flow:
    1. First tries to verify as phone OTP via Twilio
    2. If phone OTP fails, tries to verify as email code
    3. If either is correct, marks phone as verified and completes registration
    """
    permission_classes = [permissions.AllowAny]
    
    @transaction.atomic
    def post(self, request):
        serializer = CheckOTPSerializer(data=request.data)
        
        if not serializer.is_valid():
            return Response({
                "success": False,
                "errors": serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)
        
        phone = serializer.validated_data['phone']
        code = serializer.validated_data['code']
        
        # Format phone number
        try:
            formatted_phone = format_phone_number(phone)
        except Exception as e:
            return Response({
                "success": False,
                "message": f"Invalid phone number format: {str(e)}"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # First, try to verify as phone OTP via Twilio
        otp_result = check_otp(formatted_phone, code)
        verified_via = None
        
        if otp_result['success'] and otp_result.get('approved'):
            # Phone OTP is correct
            verified_via = 'phone'
        else:
            # Phone OTP failed, try email code
            try:
                variants = phone_variants_for_lookup(formatted_phone)
                profile = Profile.objects.filter(phone__in=variants).first() if variants else None
                if not profile:
                    raise Profile.DoesNotExist()

                user = profile.user
                user_email = user.email
                
                if user_email:
                    email_result = verify_email_code(user, user_email, code)
                    if email_result['success'] and email_result.get('approved'):
                        verified_via = 'email'
                    else:
                        # Both failed
                        return Response({
                            "success": False,
                            "message": "Invalid verification code. Please enter the correct OTP code or email verification code.",
                            "approved": False
                        }, status=status.HTTP_400_BAD_REQUEST)
                else:
                    # No email, so only phone OTP is valid
                    return Response({
                        "success": False,
                        "message": otp_result['message'],
                        "status": otp_result.get('status', 'error'),
                        "error_code": otp_result.get('error_code'),
                        "approved": False
                    }, status=status.HTTP_400_BAD_REQUEST)
            except Profile.DoesNotExist:
                # User doesn't exist, so only phone OTP is valid
                return Response({
                    "success": False,
                    "message": otp_result['message'],
                    "status": otp_result.get('status', 'error'),
                    "error_code": otp_result.get('error_code'),
                    "approved": False
                }, status=status.HTTP_400_BAD_REQUEST)
        
        # Code is correct (either phone OTP or email code) - mark phone as verified
        try:
            variants = phone_variants_for_lookup(formatted_phone)
            profile = Profile.objects.filter(phone__in=variants).first() if variants else None
            if not profile:
                raise Profile.DoesNotExist()

            update_fields = ["phone_verified"]
            profile.phone_verified = True
            if (profile.phone or "") != formatted_phone:
                profile.phone = formatted_phone
                update_fields.append("phone")
            profile.save(update_fields=update_fields)
            
            user = profile.user
            
            # Log activity
            try:
                UserActivity.objects.create(
                    user=user,
                    activity_type=UserActivity.ActivityType.PROFILE_UPDATE,
                    description=f"Phone number verified via {verified_via}: {formatted_phone}",
                    ip_address=request.META.get('REMOTE_ADDR'),
                    user_agent=request.META.get('HTTP_USER_AGENT', '')
                )
            except Exception:
                pass
            
            return Response({
                "success": True,
                "message": f"Verification code is correct (verified via {verified_via})",
                "approved": True,
                "user_id": user.id,
                "phone_verified": True,
                "verified_via": verified_via
            }, status=status.HTTP_200_OK)
        
        except Profile.DoesNotExist:
            # Phone number not found in database
            # This might be a new registration - return success but note that user needs to be created
            return Response({
                "success": True,
                "message": "Verification code is correct, but phone number not found in database. Please complete registration.",
                "approved": True,
                "phone_verified": False,
                "requires_registration": True,
                "verified_via": verified_via
            }, status=status.HTTP_200_OK)
        
        except Exception as e:
            return Response({
                "success": False,
                "message": f"Error updating phone verification: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class RegisterWithOTPView(APIView):
    """
    Register or Login with OTP - Complete API for mobile app
    POST /api/accounts/register-with-otp/
    Body: {
        "phone": "+491234567890",
        "code": "123456",
        "name": "John Doe",  // Required only for new users
        "email": "john@example.com",  // Optional
        "password": "password123",  // Required only for new users
        "interests": ["food", "travel"]  // Optional
    }
    
    Flow:
    1. Verifies OTP code
    2. If user exists: marks phone as verified and returns tokens
    3. If user doesn't exist: creates new user and returns tokens
    
    Returns JWT tokens and user data on success
    """
    permission_classes = [permissions.AllowAny]
    throttle_classes = [OTPThrottle]
    
    def get_client_ip(self, request):
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            return x_forwarded_for.split(',')[0].strip()
        return request.META.get('REMOTE_ADDR') or ''
    
    @transaction.atomic
    def post(self, request):
        # Get phone number first to check if it's a test number
        phone = request.data.get('phone', '').strip()
        if not phone:
            return Response({
                "success": False,
                "errors": {"phone": ["Phone number is required"]}
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Format phone number early to check if it's a test number
        try:
            formatted_phone = format_phone_number(phone)
        except Exception as e:
            return Response({
                "success": False,
                "message": f"Invalid phone number format: {str(e)}"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Check if this is a test number that's already verified - make code optional
        variants = phone_variants_for_lookup(formatted_phone)
        is_test_number = any(variant in UNLIMITED_OTP_PHONES for variant in variants)
        skip_otp_verification = False
        found_profile = None
        
        # Try to find profile with any phone variant (e.g., stored without +49)
        try:
            found_profile = Profile.objects.filter(phone__in=variants).first() if variants else None
        except Exception:
            found_profile = None

        # Canonicalize stored phone to E.164 if we found a profile
        if found_profile:
            try:
                if (found_profile.phone or "") != formatted_phone:
                    found_profile.phone = formatted_phone
                    found_profile.save(update_fields=["phone"])
            except Exception:
                pass
        
        # Removed skip_otp_verification - all users must provide valid OTP code
        # if is_test_number and found_profile:
        #     if found_profile.phone_verified:
        #         skip_otp_verification = True
        elif found_profile and found_profile.phone_verified:
            # Even if not in test list, if phone is verified, we can allow login
            # But still require OTP for security
            pass
        
        # Now validate the serializer
        reg_data = request.data.copy() if hasattr(request.data, "copy") else dict(request.data)
        # Removed default test code - users must provide valid OTP

        serializer = RegisterWithOTPSerializer(data=reg_data)
        
        if not serializer.is_valid():
            # Log validation errors for debugging
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"RegisterWithOTP validation failed for {formatted_phone}: {serializer.errors}")
            return Response({
                "success": False,
                "errors": serializer.errors,
                "message": "Validation failed. Please check the errors."
            }, status=status.HTTP_400_BAD_REQUEST)
        
        code = serializer.validated_data['code']
        
        # Verify code - try phone OTP first, then email code
        if skip_otp_verification:
            # For test numbers that are already verified, accept any code for testing
            otp_result = {'success': True, 'approved': True, 'status': 'approved'}
            verified_via = 'test_bypass'
        else:
            otp_result = check_otp(formatted_phone, code)
            verified_via = None
        
        if otp_result['success'] and otp_result.get('approved'):
            # Phone OTP is correct
            verified_via = 'phone'
        else:
            # Phone OTP failed, try email code
            try:
                profile = found_profile
                if not profile:
                    variants = phone_variants_for_lookup(formatted_phone)
                    profile = Profile.objects.filter(phone__in=variants).first() if variants else None
                if not profile:
                    raise Profile.DoesNotExist()
                user = profile.user
                user_email = user.email
                
                if user_email:
                    email_result = verify_email_code(user, user_email, code)
                    if email_result['success'] and email_result.get('approved'):
                        verified_via = 'email'
                    else:
                        # Both failed
                        return Response({
                            "success": False,
                            "message": "Invalid verification code. Please enter the correct OTP code or email verification code.",
                            "approved": False
                        }, status=status.HTTP_400_BAD_REQUEST)
                else:
                    # No email, so only phone OTP is valid
                    if not otp_result['success']:
                        return Response({
                            "success": False,
                            "message": otp_result['message'],
                            "status": otp_result.get('status', 'error'),
                            "error_code": otp_result.get('error_code')
                        }, status=status.HTTP_400_BAD_REQUEST)
                    if not otp_result['approved']:
                        return Response({
                            "success": False,
                            "message": otp_result['message'],
                            "approved": False
                        }, status=status.HTTP_400_BAD_REQUEST)
            except Profile.DoesNotExist:
                # User doesn't exist yet, so only phone OTP is valid
                if not otp_result['success']:
                    return Response({
                        "success": False,
                        "message": otp_result['message'],
                        "status": otp_result.get('status', 'error'),
                        "error_code": otp_result.get('error_code')
                    }, status=status.HTTP_400_BAD_REQUEST)
                if not otp_result.get('approved'):
                    return Response({
                        "success": False,
                        "message": otp_result.get('message', 'Invalid verification code'),
                        "approved": False
                    }, status=status.HTTP_400_BAD_REQUEST)
                verified_via = 'phone'  # User doesn't exist, verified via phone OTP

        # TEMP QA mode: always force client to complete registration screen (no tokens)
        try:
            if getattr(settings, "TEST_FORCE_REGISTRATION_AFTER_OTP", False):
                return Response({
                    "success": True,
                    "message": "OTP verified. Please complete registration (QA mode).",
                    "approved": True,
                    "phone_verified": True,
                    "verified_via": verified_via,
                    "requires_registration": True,
                    "phone": formatted_phone,
                }, status=status.HTTP_200_OK)
        except Exception:
            pass
        
        # Code is correct (either phone OTP or email code) - check if user exists
        # Use found_profile if we already found it, otherwise try to get it
        try:
            if found_profile:
                profile = found_profile
            else:
                variants = phone_variants_for_lookup(formatted_phone)
                profile = Profile.objects.filter(phone__in=variants).first() if variants else None
                if not profile:
                    raise Profile.DoesNotExist()
            # User exists - mark phone as verified and return tokens
            update_fields = ["phone_verified"]
            profile.phone_verified = True
            if (profile.phone or "") != formatted_phone:
                profile.phone = formatted_phone
                update_fields.append("phone")
            profile.save(update_fields=update_fields)
            
            user = profile.user
            
            # Log activity
            try:
                UserActivity.objects.create(
                    user=user,
                    activity_type=UserActivity.ActivityType.LOGIN,
                    description=f"Phone verified and logged in via {verified_via}: {formatted_phone}",
                    ip_address=self.get_client_ip(request),
                    user_agent=request.META.get('HTTP_USER_AGENT', '')
                )
            except Exception:
                pass
            
            # Generate JWT tokens
            refresh = RefreshToken.for_user(user)
            
            return Response({
                "success": True,
                "message": f"Verification code is correct (verified via {verified_via})",
                "approved": True,
                "phone_verified": True,
                "verified_via": verified_via,
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "user": UserSerializer(user).data,
                "profile": ProfileSerializer(profile).data,
                "is_new_user": False
            }, status=status.HTTP_200_OK)
        
        except Profile.DoesNotExist:
            # New user: ONLY verify OTP here. Client must complete registration via /api/accounts/register/
            return Response({
                "success": True,
                "message": "Verification code is correct. Please complete registration.",
                "approved": True,
                "phone_verified": True,
                "verified_via": verified_via,
                "is_new_user": True,
                "requires_registration": True,
                "phone": formatted_phone,
            }, status=status.HTTP_200_OK)
        
        except Exception as e:
            import logging
            logging.getLogger(__name__).exception("RegisterWithOTP 500: %s", e)
            return Response({
                "success": False,
                "message": f"Error processing registration: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)