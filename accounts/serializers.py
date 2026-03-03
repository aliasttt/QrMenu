from __future__ import annotations

from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
import re

from .models import Profile, UserActivity, Business, EmailVerificationCode


class SendOTPSerializer(serializers.Serializer):
    """Serializer for sending OTP"""
    # Accept both keys for backward compatibility (some clients send "number")
    phone = serializers.CharField(required=False, allow_blank=True, help_text="Phone number (supports European formats)")
    number = serializers.CharField(required=False, allow_blank=True, help_text="Alias for phone")

    def validate(self, attrs):
        phone = (attrs.get("phone") or attrs.get("number") or "").strip()
        if not phone:
            raise serializers.ValidationError({"phone": "Phone number is required"})
        attrs["phone"] = phone
        return attrs


class CheckOTPSerializer(serializers.Serializer):
    """Serializer for verifying OTP"""
    phone = serializers.CharField(required=False, allow_blank=True, help_text="Phone number")
    number = serializers.CharField(required=False, allow_blank=True, help_text="Alias for phone")
    code = serializers.CharField(required=True, min_length=4, max_length=10, help_text="OTP code")
    
    def validate(self, attrs):
        phone = (attrs.get("phone") or attrs.get("number") or "").strip()
        if not phone:
            raise serializers.ValidationError({"phone": "Phone number is required"})
        attrs["phone"] = phone
        return attrs
    
    def validate_code(self, value):
        """Validate OTP code format"""
        code = value.strip()
        if not code:
            raise serializers.ValidationError("OTP code is required")
        if not code.isdigit():
            raise serializers.ValidationError("OTP code must contain only digits")
        return code


class RegisterWithOTPSerializer(serializers.Serializer):
    """Serializer for verifying with OTP.

    NOTE: This serializer is used by RegisterWithOTPView.
    For new users, we only verify OTP here and then the client completes registration via /api/accounts/register/.
    """
    phone = serializers.CharField(required=True, help_text="Phone number")
    code = serializers.CharField(required=True, min_length=4, max_length=10, help_text="OTP code")
    # Optional fields for new user registration
    name = serializers.CharField(required=False, allow_blank=True, help_text="User name (required for new users)")
    email = serializers.EmailField(required=False, allow_blank=True, help_text="Email address (optional)")
    password = serializers.CharField(write_only=True, required=False, min_length=8, help_text="Password (required for new users)")
    interests = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        allow_empty=True,
        help_text="List of user interests"
    )
    
    def validate_phone(self, value):
        """Validate phone number format"""
        phone = value.strip()
        if not phone:
            raise serializers.ValidationError("Phone number is required")
        return phone
    
    def validate_code(self, value):
        """Validate OTP code format"""
        code = value.strip()
        if not code:
            raise serializers.ValidationError("OTP code is required")
        if not code.isdigit():
            raise serializers.ValidationError("OTP code must contain only digits")
        return code
    
    def validate(self, attrs):
        """Normalize phone. No profile creation validation here."""
        phone = attrs.get('phone', '').strip()
        
        # Format phone number early for consistent lookups
        formatted_phone = phone
        try:
            from .twilio_utils import format_phone_number, phone_variants_for_lookup
            formatted_phone = format_phone_number(phone)
            # Update attrs with formatted phone
            attrs['phone'] = formatted_phone
        except Exception:
            # If formatting fails, use original phone (will be handled in view)
            formatted_phone = phone
        
        return attrs


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "first_name", "last_name", "email", "date_joined", "is_active"]
        read_only_fields = ["id", "date_joined"]


class ProfileSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    last_activity = serializers.SerializerMethodField()
    interests = serializers.SerializerMethodField()

    class Meta:
        model = Profile
        fields = [
            "id", "user", "role", "phone", "phone_verified", "business_name", "is_active",
            "last_login_ip", "created_at", "updated_at", "business_type",
            "business_address", "business_phone", "total_logins", "last_activity",
            "interests"
        ]
        read_only_fields = ["id", "created_at", "updated_at", "last_login_ip", "total_logins", "phone_verified"]

    def get_last_activity(self, obj):
        """Never return null: use last_activity, then updated_at, then created_at, then now (ISO)."""
        from django.utils import timezone
        value = getattr(obj, "last_activity", None)
        if value is not None:
            return value.isoformat() if hasattr(value, "isoformat") else value
        value = getattr(obj, "updated_at", None)
        if value is not None:
            return value.isoformat() if hasattr(value, "isoformat") else value
        value = getattr(obj, "created_at", None)
        if value is not None:
            return value.isoformat() if hasattr(value, "isoformat") else value
        return timezone.now().isoformat()

    def get_interests(self, obj):
        """Never return empty: use profile.interests or default ["general"]."""
        value = getattr(obj, "interests", None)
        if isinstance(value, list) and len(value) > 0:
            return value
        return ["general"]


class RegisterSerializer(serializers.Serializer):
    # Accept both `number` and `phone` for backward compatibility with mobile clients.
    number = serializers.CharField(required=False, allow_blank=True, help_text="Phone number")
    phone = serializers.CharField(required=False, allow_blank=True, help_text="Alias for number")
    name = serializers.CharField(required=True, help_text="User name")
    # Email is optional for mobile registration (some clients don't collect it yet).
    email = serializers.EmailField(required=False, allow_blank=True, help_text="Email address (optional)")
    password = serializers.CharField(write_only=True, required=True)
    confirmPassword = serializers.CharField(write_only=True, required=False, allow_blank=True)
    favorit = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        allow_empty=True,
        help_text="List of user favorites/interests"
    )
    # Optional fields for backward compatibility
    last_name = serializers.CharField(required=False, allow_blank=True)
    role = serializers.ChoiceField(choices=Profile.Role.choices, default=Profile.Role.CUSTOMER, required=False)

    def validate_name(self, value: str) -> str:
        # Check minimum length (8 characters) for name
        if len(value.strip()) < 8:
            raise serializers.ValidationError("Name must be at least 8 characters long.")
        return value.strip()
    
    def validate_password(self, value: str) -> str:
        # Only check minimum length (8 characters), skip CommonPasswordValidator
        # This allows passwords like "123qwe123" which are acceptable for mobile apps
        if len(value) < 8:
            raise serializers.ValidationError("Password must be at least 8 characters long.")
        return value
    
    def validate(self, attrs):
        # Normalize input aliases
        if not (attrs.get("number") or "").strip():
            attrs["number"] = (attrs.get("phone") or "").strip()

        # Some clients send confirm_password instead of confirmPassword
        if not (attrs.get("confirmPassword") or "").strip():
            raw = getattr(self, "initial_data", {}) or {}
            alt = (raw.get("confirm_password") or raw.get("confirm") or "").strip()
            if alt:
                attrs["confirmPassword"] = alt

        password = attrs.get('password')
        confirm_password = attrs.get('confirmPassword')
        
        if not confirm_password:
            raise serializers.ValidationError({"confirmPassword": "Confirm password is required"})
        if password and password != confirm_password:
            raise serializers.ValidationError({"confirmPassword": "Passwords don't match"})
        
        # Check if phone number already exists (normalize so +90... and 055... match)
        phone = attrs.get('number', '').strip()
        if phone:
            try:
                from .twilio_utils import format_phone_number, phone_variants_for_lookup
                formatted = format_phone_number(phone)
                attrs["number"] = formatted
                variants = phone_variants_for_lookup(formatted)
                if variants and Profile.objects.filter(phone__in=variants).exists():
                    raise serializers.ValidationError({"number": "A user with this phone number already exists"})
            except serializers.ValidationError:
                raise
            except Exception:
                if Profile.objects.filter(phone__iexact=phone).exists():
                    raise serializers.ValidationError({"number": "A user with this phone number already exists"})
        
        # Check if email already exists (email must be unique)
        email = (attrs.get('email', '') or "").strip()
        if email and User.objects.filter(email__iexact=email).exists():
            raise serializers.ValidationError({"email": "This email is already registered."})
        
        return attrs

    def create(self, validated_data):
        password = validated_data.pop("password")
        confirm_password = validated_data.pop("confirmPassword")
        phone = validated_data.pop("number", "").strip()
        name = validated_data.pop("name", "").strip()
        interests = validated_data.pop("favorit", [])
        role = validated_data.pop("role", Profile.Role.CUSTOMER)
        
        # Split name into first_name and last_name if needed
        name_parts = name.split(maxsplit=1)
        first_name = name_parts[0] if name_parts else ""
        last_name = name_parts[1] if len(name_parts) > 1 else validated_data.pop("last_name", "")
        
        # Normalize phone for storage (E.164) and generate a safe username
        try:
            from .twilio_utils import format_phone_number
            phone = format_phone_number(phone)
        except Exception:
            pass

        phone_digits = re.sub(r"\D", "", phone)
        username = f"user_{phone_digits or phone}"
        
        # Ensure username is unique
        base_username = username
        counter = 1
        while User.objects.filter(username=username).exists():
            username = f"{base_username}_{counter}"
            counter += 1
        
        # Create user (email will be set after verification if provided)
        email = (validated_data.pop("email", "") or "").strip()
        user = User.objects.create(
            username=username,
            first_name=first_name,
            last_name=last_name,
            email="",  # Email will be set after verification
            **validated_data
        )
        user.set_password(password)
        user.save(update_fields=["password"])
        
        # Create or update profile
        profile, _ = Profile.objects.get_or_create(user=user)
        profile.role = role if role != Profile.Role.SUPERUSER else Profile.Role.CUSTOMER
        profile.phone = phone
        
        # Store favorites/interests in interests field
        if interests:
            profile.interests = interests
        
        profile.save(update_fields=["role", "phone", "interests"])

        # Keep loyalty.Customer in sync so phone shows in Super Admin -> Loyalty -> Customer
        try:
            from loyalty.models import Customer as LoyaltyCustomer
            customer, _ = LoyaltyCustomer.objects.get_or_create(user=user)
            if (customer.phone or "") != phone:
                customer.phone = phone
                customer.save(update_fields=["phone"])
        except Exception:
            pass
        
        # Generate and send verification code only if email provided
        if email:
            from django.utils import timezone
            from datetime import timedelta
            import random
            
            verification_code = str(random.randint(100000, 999999))
            expires_at = timezone.now() + timedelta(minutes=10)  # Code expires in 10 minutes
            
            EmailVerificationCode.objects.create(
                user=user,
                email=email,
                code=verification_code,
                expires_at=expires_at
            )
            
            # Send verification email
            from django.core.mail import send_mail
            try:
                send_mail(
                    subject='Email Verification Code - Bonus',
                    message=f'Your verification code is: {verification_code}\n\nThis code will expire in 10 minutes.',
                    from_email=None,  # Uses DEFAULT_FROM_EMAIL from settings
                    recipient_list=[email],
                    fail_silently=False,
                )
            except Exception:
                # Log error but don't fail registration
                pass
        
        return user


class UserActivitySerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    activity_type_display = serializers.CharField(source='get_activity_type_display', read_only=True)
    
    class Meta:
        model = UserActivity
        fields = [
            "id", "user", "activity_type", "activity_type_display", "description",
            "ip_address", "user_agent", "created_at"
        ]
        read_only_fields = ["id", "created_at"]


class BusinessSerializer(serializers.ModelSerializer):
    owner = UserSerializer(read_only=True)
    
    class Meta:
        model = Business
        fields = [
            "id", "owner", "name", "business_type", "address", "phone", "email",
            "is_active", "created_at", "updated_at", "total_customers",
            "total_campaigns", "total_revenue"
        ]
        read_only_fields = ["id", "created_at", "updated_at", "total_customers", "total_campaigns", "total_revenue"]


class UserManagementSerializer(serializers.ModelSerializer):
    profile = ProfileSerializer(read_only=True)
    full_name = serializers.SerializerMethodField()
    
    class Meta:
        model = User
        fields = [
            "id", "username", "email", "first_name", "last_name", "full_name",
            "date_joined", "is_active", "profile"
        ]
        read_only_fields = ["id", "date_joined"]
    
    def get_full_name(self, obj):
        return f"{obj.first_name} {obj.last_name}".strip() or obj.username


class DashboardStatsSerializer(serializers.Serializer):
    users = serializers.DictField()
    businesses = serializers.DictField()
    activities = serializers.DictField()
    revenue = serializers.DictField()