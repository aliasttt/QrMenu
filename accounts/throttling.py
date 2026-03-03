"""
Custom throttling classes for rate limiting
"""

from django.conf import settings
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle


class LoginThrottle(AnonRateThrottle):
    """
    Throttle for login attempts to prevent brute force attacks
    """
    rate = '5/minute'  # 5 login attempts per minute for anonymous users


class RegisterThrottle(AnonRateThrottle):
    """
    Throttle for registration attempts
    """
    # Default was too low for NAT/shared IPs and QA retries.
    # Can be overridden by env var REGISTER_THROTTLE_RATE.
    # If TEST_OTP_OVERRIDE_CODE is set (QA mode), we relax the default further.
    rate = (
        getattr(settings, "REGISTER_THROTTLE_RATE", None)
        or ("60/hour" if getattr(settings, "TEST_OTP_OVERRIDE_CODE", None) else "30/hour")
    )


class OTPThrottle(AnonRateThrottle):
    """
    Throttle for OTP requests to prevent abuse.
    Rate can be tuned via OTP_THROTTLE_RATE env setting.
    """
    rate = getattr(settings, "OTP_THROTTLE_RATE", "5/minute")


class PasswordResetThrottle(AnonRateThrottle):
    """
    Throttle for password reset requests
    """
    rate = '3/hour'  # 3 password reset requests per hour per IP

