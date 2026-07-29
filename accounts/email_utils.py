"""
Email utility functions for sending verification codes via email
"""
import random
from datetime import timedelta
from django.conf import settings
from django.utils import timezone
from django.core.cache import cache
from .models import EmailVerificationCode
from .email_safety import (
    acquire_email_cooldown,
    check_email_action,
    get_configured_email_connection,
    normalize_email_address,
    safe_send_mail,
    validate_recipient_email,
)


def send_email_verification_code(user, email, request=None, action="email_verification"):
    """
    Send a 6-digit verification code to the user's email
    
    Args:
        user: User instance
        email: Email address to send code to
    
    Returns:
        dict: {
            'success': bool,
            'message': str,
            'code': str (only in DEBUG mode)
        }
    """
    try:
        email = validate_recipient_email(email)
        allowed, reason = check_email_action(action, email, request=request)
        if not allowed:
            return {"success": False, "message": f"rate_limited:{reason}", "rate_limited": True}
        if not acquire_email_cooldown(action, email):
            return {"success": False, "message": "cooldown_active", "rate_limited": True}

        # Generate 6-digit code
        code = str(random.randint(100000, 999999))
        
        # Set expiration time (10 minutes)
        expires_at = timezone.now() + timedelta(minutes=10)
        
        # Delete old codes for this user and email
        EmailVerificationCode.objects.filter(
            user=user,
            email__iexact=email,
            is_verified=False
        ).delete()
        
        # Create new verification code
        EmailVerificationCode.objects.create(
            user=user,
            email=email,
            code=code,
            expires_at=expires_at
        )
        
        # Prepare email content (English for German market)
        subject = "Your Login Verification Code"
        message = f"""Hello,

Your login verification code:
{code}

This code is valid for 10 minutes.

If you did not request this, please ignore this email.

Best regards,
Bonus Berlin Team
"""
        
        # Bonus app requirement: send emails from info@mybonusberlin.com (or BONUS_FROM_EMAIL)
        from_email = getattr(settings, "BONUS_FROM_EMAIL", getattr(settings, "DEFAULT_FROM_EMAIL", None))

        # Always send via SMTP (Bonus SMTP if configured)
        connection = get_configured_email_connection(timeout=30)

        try:
            safe_send_mail(
                action=action,
                subject=subject,
                message=message,
                from_email=from_email,
                recipient_list=[email],
                fail_silently=False,
                connection=connection,
            )

            result = {
                'success': True,
                'message': 'Verification code sent to your email'
            }

            # In DEBUG mode, also return the code for testing (but the email is still sent)
            if settings.DEBUG:
                result['code'] = code
                result['message'] = f'Verification code sent to your email. Code: {code}'

            return result
        except Exception as e:
            # If sending fails, return failure (in DEBUG include the code for manual testing)
            error_message = f'Error sending email: {str(e)}'

            if settings.DEBUG:
                return {
                    'success': False,
                    'message': error_message,
                    'code': code,
                    'error': str(e)
                }

            return {
                'success': False,
                'message': error_message
            }
    
    except Exception as e:
        return {
            'success': False,
            'message': f'Error creating verification code: {str(e)}'
        }


def verify_email_code(user, email, code):
    """
    Verify the email verification code entered by user
    
    Args:
        user: User instance
        email: Email address
        code: 6-digit code entered by user
    
    Returns:
        dict: {
            'success': bool,
            'approved': bool,
            'message': str
        }
    """
    try:
        email = normalize_email_address(email)
        # Find the most recent unverified code for this user and email
        verification = EmailVerificationCode.objects.filter(
            user=user,
            email__iexact=email,
            code=code,
            is_verified=False
        ).order_by('-created_at').first()
        
        if not verification:
            return {
                'success': False,
                'approved': False,
                'message': 'Invalid verification code'
            }
        
        # Check if code is expired
        if verification.is_expired():
            return {
                'success': False,
                'approved': False,
                'message': 'Verification code has expired. Please request a new code'
            }
        
        # Mark code as verified
        verification.is_verified = True
        verification.save(update_fields=['is_verified'])
        
        return {
            'success': True,
            'approved': True,
            'message': 'Verification code is correct'
        }
    
    except Exception as e:
        return {
            'success': False,
            'approved': False,
            'message': f'Error verifying code: {str(e)}'
        }
