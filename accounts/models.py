from __future__ import annotations

from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone


class Profile(models.Model):
    class Role(models.TextChoices):
        SUPERUSER = "superuser", "Super User"
        ADMIN = "admin", "Admin"
        OPERATOR = "operator", "Operator"
        BUSINESS_ADMIN = "business_admin", "Business Admin"
        CUSTOMER = "customer", "Customer"
        # Legacy support - will be removed in future
        BUSINESS_OWNER = "business_owner", "Business Owner"  # Deprecated: use BUSINESS_ADMIN

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    role = models.CharField(max_length=32, choices=Role.choices, default=Role.CUSTOMER)
    phone = models.CharField(max_length=32, blank=True)
    phone_verified = models.BooleanField(default=False, help_text="Whether the phone number has been verified via OTP")
    business_name = models.CharField(max_length=200, blank=True)
    is_active = models.BooleanField(default=True)
    last_login_ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # User interests/favorites (stored as JSON)
    interests = models.JSONField(default=list, blank=True, help_text="List of user interests/favorites")
    
    # Additional fields for business owners
    business_type = models.CharField(max_length=100, blank=True)
    business_address = models.TextField(blank=True)
    business_phone = models.CharField(max_length=32, blank=True)
    
    # Activity tracking
    total_logins = models.PositiveIntegerField(default=0)
    last_activity = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.user.username} ({self.role})"
    
    def is_superuser_role(self):
        return self.role == self.Role.SUPERUSER
    
    def is_admin_role(self):
        return self.role == self.Role.ADMIN
    
    def is_business_admin_role(self):
        """Check if user is business admin (includes legacy business_owner for backward compatibility)"""
        return self.role in [self.Role.BUSINESS_ADMIN, self.Role.BUSINESS_OWNER]
    
    def is_business_owner_role(self):
        """Deprecated: use is_business_admin_role instead"""
        return self.is_business_admin_role()
    
    def update_activity(self, ip_address=None):
        self.last_activity = timezone.now()
        self.total_logins += 1
        if ip_address:
            self.last_login_ip = ip_address
        self.save(update_fields=['last_activity', 'total_logins', 'last_login_ip'])


class UserActivity(models.Model):
    class ActivityType(models.TextChoices):
        LOGIN = "login", "Login"
        LOGOUT = "logout", "Logout"
        PROFILE_UPDATE = "profile_update", "Profile Update"
        BUSINESS_UPDATE = "business_update", "Business Update"
        QR_GENERATE = "qr_generate", "QR Code Generated"
        CAMPAIGN_CREATE = "campaign_create", "Campaign Created"
        CUSTOMER_ADD = "customer_add", "Customer Added"
        PAYMENT_PROCESS = "payment_process", "Payment Processed"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="activities")
    activity_type = models.CharField(max_length=32, choices=ActivityType.choices)
    description = models.TextField()
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
        verbose_name_plural = "User Activities"
    
    def __str__(self):
        return f"{self.user.username} - {self.activity_type} at {self.created_at}"


class EmailVerificationCode(models.Model):
    """
    Model to store email verification codes
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="email_verification_codes")
    email = models.EmailField()
    code = models.CharField(max_length=6)
    is_verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'email', 'code']),
        ]
    
    def __str__(self):
        return f"{self.email} - {self.code} ({'verified' if self.is_verified else 'pending'})"
    
    def is_expired(self):
        from django.utils import timezone
        return timezone.now() > self.expires_at


class PasswordResetCode(models.Model):
    """
    Stores one-time numeric codes for password reset via email.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="password_reset_codes")
    email = models.EmailField()
    code = models.CharField(max_length=6)
    is_used = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'email', 'code']),
            models.Index(fields=['email', 'code']),
        ]

    def __str__(self):
        status = "used" if self.is_used else "active"
        return f"ResetCode {self.email} - {self.code} ({status})"

    def is_expired(self) -> bool:
        return timezone.now() > self.expires_at

class MenuCustomer(models.Model):
    """
    End-user account for people ordering from restaurant menus.
    Completely separate from Profile / BusinessAdmin — never mix.
    Global account: one login works across all restaurants; per-restaurant
    orders are filtered at query time (not by account scope).
    """
    email = models.EmailField(unique=True, db_index=True)
    phone = models.CharField(max_length=32, unique=True, db_index=True)
    first_name = models.CharField(max_length=120, blank=True)
    last_name = models.CharField(max_length=120, blank=True)
    password = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_login_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Menu Customer"
        verbose_name_plural = "Menu Customers"
        ordering = ["-created_at"]

    def set_password(self, raw_password: str) -> None:
        from django.contrib.auth.hashers import make_password
        self.password = make_password(raw_password)

    def check_password(self, raw_password: str) -> bool:
        from django.contrib.auth.hashers import check_password
        return check_password(raw_password, self.password)

    @property
    def name(self) -> str:
        return (f"{self.first_name} {self.last_name}").strip()

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.name or self.email or self.phone} (menu-customer #{self.pk})"


class MenuCustomerAddress(models.Model):
    customer = models.ForeignKey(
        MenuCustomer,
        on_delete=models.CASCADE,
        related_name="addresses",
    )
    label = models.CharField(max_length=64, blank=True)
    address = models.TextField()
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Menu Customer Address"
        verbose_name_plural = "Menu Customer Addresses"
        ordering = ["-is_default", "-created_at"]

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.label or 'Address'} for #{self.customer_id}"


class Business(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="businesses")
    name = models.CharField(max_length=200)
    business_type = models.CharField(max_length=100)
    address = models.TextField()
    phone = models.CharField(max_length=32)
    email = models.EmailField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Business metrics
    total_customers = models.PositiveIntegerField(default=0)
    total_campaigns = models.PositiveIntegerField(default=0)
    total_revenue = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    def __str__(self):
        return f"{self.name} ({self.owner.username})"
