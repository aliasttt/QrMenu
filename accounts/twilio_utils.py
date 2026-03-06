"""
Twilio utility functions for sending and verifying OTP codes via SMS
"""
import random
from django.conf import settings
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException
import re

# Try to use cache, fallback to in-memory dict if cache not available
try:
    from django.core.cache import cache
    USE_CACHE = True
except ImportError:
    USE_CACHE = False

# Simple in-memory cache for mock OTP codes (used when cache is not available)
_mock_otp_cache = {}

# List of phone numbers that should have unlimited OTP (for testing/admin purposes)
# OTP codes for these numbers will not be deleted after verification
UNLIMITED_OTP_PHONES = [
    '+495540225177',  # Test user (DE) – OTP 123456 only for this number
    '+905540225177',  # Admin test number
    '+905540225180',  # Business menu test number
    '+90905540225177',  # Alternative format for test number
    # 20 test business menu accounts (sequential phone numbers)
    '+905540225181', '+905540225182', '+905540225183', '+905540225184', '+905540225185',
    '+905540225186', '+905540225187', '+905540225188', '+905540225189', '+905540225190',
    '+905540225191', '+905540225192', '+905540225193', '+905540225194', '+905540225195',
    '+905540225196', '+905540225197', '+905540225198', '+905540225199', '+905540225200',
    # 20 numbers for registration testing (new user flow, OTP 123456) – usually not yet registered
    '+905540225201', '+905540225202', '+905540225203', '+905540225204', '+905540225205',
    '+905540225206', '+905540225207', '+905540225208', '+905540225209', '+905540225210',
    '+905540225211', '+905540225212', '+905540225213', '+905540225214', '+905540225215',
    '+905540225216', '+905540225217', '+905540225218', '+905540225219', '+905540225220',
]

# Hardcoded OTP codes for unlimited phones (fallback if cache is cleared)
# Format: {phone: code}
UNLIMITED_OTP_CODES = {
    '+495540225177': '123456',  # Test user (DE) – OTP 123456 only for this number
    '+905540225177': '123456',  # Admin test number
    '+905540225180': '123456',  # Business menu test number
    '+90905540225177': '123456',  # Alternative format for test number
    # 20 test business menu accounts (all use OTP 123456)
    '+905540225181': '123456', '+905540225182': '123456', '+905540225183': '123456',
    '+905540225184': '123456', '+905540225185': '123456', '+905540225186': '123456',
    '+905540225187': '123456', '+905540225188': '123456', '+905540225189': '123456',
    '+905540225190': '123456', '+905540225191': '123456', '+905540225192': '123456',
    '+905540225193': '123456', '+905540225194': '123456', '+905540225195': '123456',
    '+905540225196': '123456', '+905540225197': '123456', '+905540225198': '123456',
    '+905540225199': '123456', '+905540225200': '123456',
    # Registration testing (OTP 123456)
    '+905540225201': '123456', '+905540225202': '123456', '+905540225203': '123456',
    '+905540225204': '123456', '+905540225205': '123456', '+905540225206': '123456',
    '+905540225207': '123456', '+905540225208': '123456', '+905540225209': '123456',
    '+905540225210': '123456', '+905540225211': '123456', '+905540225212': '123456',
    '+905540225213': '123456', '+905540225214': '123456', '+905540225215': '123456',
    '+905540225216': '123456', '+905540225217': '123456', '+905540225218': '123456',
    '+905540225219': '123456', '+905540225220': '123456',
}


def get_twilio_client():
    """Get Twilio client instance"""
    account_sid = settings.TWILIO_ACCOUNT_SID
    auth_token = settings.TWILIO_AUTH_TOKEN
    
    if not account_sid or not auth_token:
        raise ValueError("Twilio credentials not configured")
    
    return Client(account_sid, auth_token)


def _send_otp_via_messaging_api(phone, client):
    """
    Fallback: Send OTP via direct Messaging API when Verify Service is blocked
    This generates OTP code manually and stores it in cache
    """
    import random
    
    # Get Twilio phone number
    incoming_numbers = client.incoming_phone_numbers.list(limit=1)
    if not incoming_numbers:
        raise ValueError("No Twilio phone number found. Please configure a phone number in Twilio Console.")
    
    from_number = incoming_numbers[0].phone_number
    
    # Generate OTP code
    otp_code = str(random.randint(100000, 999999))
    
    # Store OTP in cache
    cache_key = f'otp_direct_{phone}'
    if USE_CACHE:
        cache.set(cache_key, otp_code, 600)  # 10 minutes
    else:
        _mock_otp_cache[cache_key] = otp_code
    
    # Send SMS with English message and Alphanumeric Sender ID
    message_body = f"Welcome to MyBonusBerlin. Your verification code is {otp_code}"
    
    # Try to use Alphanumeric Sender ID "MyBonusBerlin" first
    # This will work if Sender ID is already configured in Twilio Console
    # If not available, fallback to phone number
    try:
        # Use Alphanumeric Sender ID (up to 11 characters, alphanumeric only)
        # If Sender ID is configured in Twilio, this will use it automatically
        message = client.messages.create(
            body=message_body,
            from_='MyBonusBerlin',  # Alphanumeric Sender ID (already configured in Twilio)
            to=phone
        )
    except Exception as e:
        # Fallback to phone number if Alphanumeric Sender ID is not available
        # This should not happen if Sender ID is already configured
        message = client.messages.create(
            body=message_body,
            from_=from_number,
            to=phone
        )
    
    return {
        'success': True,
        'status': message.status,
        'message': 'OTP code sent successfully',
        'channel': 'sms',
        'method': 'messaging_api',  # Indicate we used direct messaging
        'message_sid': message.sid
    }


def send_otp(phone):
    """
    Send OTP code to phone number using Twilio Verify service
    Supports European phone numbers
    
    Args:
        phone (str): Phone number in E.164 format (e.g., +1234567890, +491234567890)
    
    Returns:
        dict: {
            'success': bool,
            'status': str,
            'message': str
        }
    """
    try:
        # Format phone number to E.164 format if needed
        phone = format_phone_number(phone)

        # Test numbers: never call Twilio (avoid blocked/restricted error). Return success; user enters 123456.
        try:
            variants = phone_variants_for_lookup(phone)
            if any(v in UNLIMITED_OTP_PHONES for v in variants):
                test_code = "123456"
                for v in variants:
                    if v in UNLIMITED_OTP_CODES:
                        test_code = UNLIMITED_OTP_CODES[v]
                        break
                cache_key_direct = f"otp_direct_{phone}"
                if USE_CACHE:
                    cache.set(cache_key_direct, test_code, 600)
                else:
                    _mock_otp_cache[cache_key_direct] = test_code
                return {
                    "success": True,
                    "status": "pending",
                    "message": "OTP sent successfully.",
                    "channel": "sms",
                }
        except Exception:
            pass

        verify_sid = settings.TWILIO_VERIFY_SERVICE_SID
        
        if not verify_sid:
            # Fallback: Use Messaging API if Verify service is not configured
            return {
                'success': False,
                'status': 'error',
                'message': 'Twilio Verify Service SID not configured. Please set TWILIO_VERIFY_SERVICE_SID in settings.'
            }
        
        client = get_twilio_client()
        
        # Use v2 API (v1 is deprecated)
        verification = client.verify.v2.services(verify_sid).verifications.create(
            to=phone,
            channel='sms'  # صریحاً SMS را مشخص می‌کنیم
        )
        
        # بررسی اینکه آیا واقعاً SMS ارسال شده یا تماس صوتی
        # اگر status 'pending' باشد، معمولاً SMS ارسال شده است
        # اگر 'failed' باشد، ممکن است به تماس صوتی fallback کرده باشد
        
        message = 'OTP code sent successfully'
        
        # اگر verification.status نشان دهد که مشکلی وجود دارد، پیام مناسب بده
        if verification.status == 'failed':
            return {
                'success': False,
                'status': verification.status,
                'message': 'Failed to send SMS. Please make sure your phone number is valid and SMS is available.'
            }
        
        return {
            'success': True,
            'status': verification.status,
            'message': message,
            'channel': 'sms'  # تأیید می‌کنیم که از SMS استفاده شده است
        }
    
    except TwilioRestException as e:
        # Handle specific Twilio errors with better messages
        error_msg = e.msg or str(e)
        error_code = e.code
        
        # Check if it's a blocked/restricted number error (error code 60238)
        if error_code == 60238 or 'blocked' in error_msg.lower() or 'restricted' in error_msg.lower() or 'unable to create record' in error_msg.lower():
            # Try fallback to direct Messaging API if Verify Service is blocked
            try:
                return _send_otp_via_messaging_api(phone, client)
            except Exception as fallback_error:
                # If fallback also fails, continue with original error handling
                pass
            
            # Check if we're in DEBUG mode and should use mock OTP
            if settings.DEBUG:
                # Generate a mock OTP code for development/testing
                mock_code = str(random.randint(100000, 999999))
                cache_key = f'otp_mock_{phone}'
                
                # Store in cache or in-memory dict
                if USE_CACHE:
                    cache.set(cache_key, mock_code, 600)  # 10 minutes
                else:
                    _mock_otp_cache[cache_key] = mock_code
                
                return {
                    'success': True,
                    'status': 'pending',
                    'message': f'OTP mock code for development: {mock_code} (DEBUG mode only)',
                    'mock_code': mock_code,
                    'warning': 'Twilio blocked this number. Using mock OTP for development only.'
                }
            
            # Provide helpful guidance for production
            help_message = (
                "Your phone number is blocked/restricted by Twilio. To fix this:\n"
                "1. If you are using a Trial account, verify your phone number in Twilio Console:\n"
                "   https://console.twilio.com/us1/develop/phone-numbers/manage/verified\n"
                "2. Upgrade your Twilio account to a paid account, or\n"
                "3. Contact Twilio Support."
            )
            return {
                'success': False,
                'status': 'error',
                'message': help_message,
                'error_code': error_code,
                'error_details': error_msg
            }
        elif error_code == 60200:
            # Invalid phone number
            return {
                'success': False,
                'status': 'error',
                'message': f'Invalid phone number. Please enter the number in the correct format (e.g., +491234567890)',
                'error_code': error_code,
                'error_details': error_msg
            }
        elif error_code == 60203:
            # Max attempts reached
            return {
                'success': False,
                'status': 'error',
                'message': 'Maximum number of attempts reached. Please try again later.',
                'error_code': error_code,
                'error_details': error_msg
            }
        else:
            return {
                'success': False,
                'status': 'error',
                'message': f'Twilio error: {error_msg}',
                'error_code': error_code
            }
    except Exception as e:
        return {
            'success': False,
            'status': 'error',
            'message': f'Error sending OTP: {str(e)}'
        }


def check_otp(phone, code):
    """
    Verify OTP code entered by user
    
    Args:
        phone (str): Phone number in E.164 format
        code (str): OTP code entered by user
    
    Returns:
        dict: {
            'success': bool,
            'status': str,
            'approved': bool,
            'message': str
        }
    """
    # Format phone number to E.164 format if needed
    phone = format_phone_number(phone)

    # TEMP QA override: accept a fixed OTP code for any phone (controlled by env)
    try:
        override = getattr(settings, "TEST_OTP_OVERRIDE_CODE", None)
        if override and str(code).strip() == str(override).strip():
            # Keep a short-lived cache entry for consistency with other flows
            cache_key = f'otp_mock_{phone}'
            if USE_CACHE:
                cache.set(cache_key, str(code).strip(), 600)
            else:
                _mock_otp_cache[cache_key] = str(code).strip()
            return {
                'success': True,
                'status': 'approved',
                'approved': True,
                'message': 'OTP verified successfully (override)'
            }
    except Exception:
        pass
    
    # Debug logging
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"check_otp called: phone={phone}, code={code}, UNLIMITED_OTP_PHONES length={len(UNLIMITED_OTP_PHONES)}, phone in list={phone in UNLIMITED_OTP_PHONES}, phone in codes={phone in UNLIMITED_OTP_CODES}")
    
    # Check OTP sent via direct Messaging API (fallback method)
    cache_key_direct = f'otp_direct_{phone}'
    if USE_CACHE:
        direct_otp = cache.get(cache_key_direct)
    else:
        direct_otp = _mock_otp_cache.get(cache_key_direct)
    
    if direct_otp and code == direct_otp:
        # Don't delete OTP for unlimited phones
        if phone not in UNLIMITED_OTP_PHONES:
            if USE_CACHE:
                cache.delete(cache_key_direct)
            else:
                _mock_otp_cache.pop(cache_key_direct, None)
        return {
            'success': True,
            'status': 'approved',
            'approved': True,
            'message': 'OTP verified successfully (direct messaging)'
        }
    
    # Check hardcoded OTP for unlimited phones FIRST (works in all modes)
    if phone in UNLIMITED_OTP_PHONES and phone in UNLIMITED_OTP_CODES:
        if code == UNLIMITED_OTP_CODES[phone]:
            cache_key = f'otp_mock_{phone}'
            # Restore to cache for future use
            if USE_CACHE:
                cache.set(cache_key, code, 315360000)  # 10 years
            else:
                _mock_otp_cache[cache_key] = code
            return {
                'success': True,
                'status': 'approved',
                'approved': True,
                'message': 'OTP verified successfully (unlimited)'
            }
    
    # Check if we're using mock OTP in DEBUG mode
    if settings.DEBUG:
        cache_key = f'otp_mock_{phone}'
        if USE_CACHE:
            mock_code = cache.get(cache_key)
        else:
            mock_code = _mock_otp_cache.get(cache_key)
        
        # Check cache first
        if mock_code and code == mock_code:
            # Don't delete OTP for unlimited phones
            if phone not in UNLIMITED_OTP_PHONES:
                if USE_CACHE:
                    cache.delete(cache_key)
                else:
                    _mock_otp_cache.pop(cache_key, None)
            return {
                'success': True,
                'status': 'approved',
                'approved': True,
                'message': 'OTP verified successfully (mock)'
            }
        
        # Fallback: Check hardcoded OTP for unlimited phones
        if phone in UNLIMITED_OTP_PHONES and phone in UNLIMITED_OTP_CODES:
            if code == UNLIMITED_OTP_CODES[phone]:
                # Restore to cache for future use
                if USE_CACHE:
                    cache.set(cache_key, code, 315360000)  # 10 years
                else:
                    _mock_otp_cache[cache_key] = code
                return {
                    'success': True,
                    'status': 'approved',
                    'approved': True,
                    'message': 'OTP verified successfully (unlimited)'
                }
    
    try:
        verify_sid = settings.TWILIO_VERIFY_SERVICE_SID
        
        if not verify_sid:
            return {
                'success': False,
                'status': 'error',
                'approved': False,
                'message': 'Twilio Verify Service SID not configured'
            }
        
        client = get_twilio_client()
        
        # Use v2 API (v1 is deprecated)
        verification_check = client.verify.v2.services(verify_sid).verification_checks.create(
            to=phone,
            code=code
        )
        
        approved = verification_check.status == 'approved'
        
        return {
            'success': True,
            'status': verification_check.status,
            'approved': approved,
            'message': 'OTP verified successfully' if approved else 'Invalid OTP code'
        }
    
    except TwilioRestException as e:
        # Handle specific Twilio errors
        # First check hardcoded OTP for unlimited phones (works in all modes)
        if phone in UNLIMITED_OTP_PHONES and phone in UNLIMITED_OTP_CODES:
            if code == UNLIMITED_OTP_CODES[phone]:
                cache_key = f'otp_mock_{phone}'
                if USE_CACHE:
                    cache.set(cache_key, code, 315360000)  # 10 years
                else:
                    _mock_otp_cache[cache_key] = code
                return {
                    'success': True,
                    'status': 'approved',
                    'approved': True,
                    'message': 'OTP verified successfully (unlimited)'
                }
        
        if e.code == 20404:
            # Check if we're using mock OTP in DEBUG mode
            if settings.DEBUG:
                cache_key = f'otp_mock_{phone}'
                if USE_CACHE:
                    mock_code = cache.get(cache_key)
                else:
                    mock_code = _mock_otp_cache.get(cache_key)
                
                if mock_code and code == mock_code:
                    # Don't delete OTP for unlimited phones
                    if phone not in UNLIMITED_OTP_PHONES:
                        if USE_CACHE:
                            cache.delete(cache_key)
                        else:
                            _mock_otp_cache.pop(cache_key, None)
                    return {
                        'success': True,
                        'status': 'approved',
                        'approved': True,
                        'message': 'OTP verified successfully (mock)'
                    }
                
                # Fallback: Check hardcoded OTP for unlimited phones
                if phone in UNLIMITED_OTP_PHONES and phone in UNLIMITED_OTP_CODES:
                    if code == UNLIMITED_OTP_CODES[phone]:
                        # Restore to cache for future use
                        if USE_CACHE:
                            cache.set(cache_key, code, 315360000)  # 10 years
                        else:
                            _mock_otp_cache[cache_key] = code
                        return {
                            'success': True,
                            'status': 'approved',
                            'approved': True,
                            'message': 'OTP verified successfully (unlimited)'
                        }
            
            return {
                'success': False,
                'status': 'error',
                'approved': False,
                'message': 'Verification not found. Please request a new code.'
            }
        elif e.code == 20403:
            # Check if we're using mock OTP in DEBUG mode
            if settings.DEBUG:
                cache_key = f'otp_mock_{phone}'
                if USE_CACHE:
                    mock_code = cache.get(cache_key)
                else:
                    mock_code = _mock_otp_cache.get(cache_key)
                
                if mock_code and code == mock_code:
                    # Don't delete OTP for unlimited phones
                    if phone not in UNLIMITED_OTP_PHONES:
                        if USE_CACHE:
                            cache.delete(cache_key)
                        else:
                            _mock_otp_cache.pop(cache_key, None)
                    return {
                        'success': True,
                        'status': 'approved',
                        'approved': True,
                        'message': 'OTP verified successfully (mock)'
                    }
                
                # Fallback: Check hardcoded OTP for unlimited phones
                if phone in UNLIMITED_OTP_PHONES and phone in UNLIMITED_OTP_CODES:
                    if code == UNLIMITED_OTP_CODES[phone]:
                        # Restore to cache for future use
                        if USE_CACHE:
                            cache.set(cache_key, code, 315360000)  # 10 years
                        else:
                            _mock_otp_cache[cache_key] = code
                        return {
                            'success': True,
                            'status': 'approved',
                            'approved': True,
                            'message': 'OTP verified successfully (unlimited)'
                        }
            
            return {
                'success': False,
                'status': 'error',
                'approved': False,
                'message': 'Invalid verification code'
            }
        else:
            return {
                'success': False,
                'status': 'error',
                'approved': False,
                'message': f'Twilio error: {e.msg}',
                'error_code': e.code
            }
    except Exception as e:
        return {
            'success': False,
            'status': 'error',
            'approved': False,
            'message': f'Error verifying OTP: {str(e)}'
        }


def format_phone_number(phone):
    """
    Format phone number to E.164 with +49 only (Germany). For bonus app / Twilio.
    Every number is normalized to +49 so Twilio sends SMS with German country code.
    """
    if not phone:
        return ""

    default_cc = "49"

    normalized = _normalize_to_plus_digits(phone)
    if not normalized:
        return ""

    # Only +49 is supported; if input has +90 or +98 (legacy/test), treat as digits and prefix +49
    digits_only = re.sub(r"\D", "", normalized)
    if normalized.startswith("+49") and len(digits_only) > 2:
        e164 = "+49" + digits_only[2:]
    else:
        # Treat as German national: strip leading 0, then +49 + rest
        if digits_only.startswith("49") and len(digits_only) > len("49") + 5:
            nsn = digits_only[2:]
            if nsn.startswith("0"):
                nsn = nsn[1:]
            e164 = f"+49{nsn}"
        else:
            if digits_only.startswith("0"):
                digits_only = digits_only[1:]
            e164 = f"+{default_cc}{digits_only}"

    # Germany: drop trunk 0 after +49
    if e164.startswith("+49") and len(e164) > 3 and e164[3] == "0":
        e164 = "+49" + e164[4:]

    return e164


def _normalize_to_plus_digits(phone: str) -> str:
    """
    Normalize to either:
    - '+<digits>' (if input had a leading '+' or '00' international prefix), or
    - '<digits>' (national / unknown prefix)
    """
    if phone is None:
        return ""
    s = str(phone).strip()
    if not s:
        return ""

    # Convert international prefix 00 -> +
    if s.startswith("00"):
        digits = re.sub(r"\D", "", s)
        return "+" + digits[2:] if len(digits) > 2 else "+"

    has_plus = s.startswith("+")
    digits = re.sub(r"\D", "", s)
    if not digits and not has_plus:
        return ""
    return ("+" if has_plus else "") + digits


def phone_variants_for_lookup(phone: str) -> set[str]:
    """
    Generate phone variants so DB lookup works with/without '+49' and common formatting.
    This is intentionally conservative: it always includes canonical E.164 plus a few
    common alternates that might exist in legacy DB rows.
    """
    variants: set[str] = set()
    base = _normalize_to_plus_digits(phone)
    if not base:
        return variants

    variants.add(base)
    variants.add(base.lstrip("+"))

    try:
        e164 = format_phone_number(phone)
    except Exception:
        e164 = ""

    if e164:
        variants.add(e164)
        variants.add(e164.lstrip("+"))
        # Germany only: national with leading 0 (e.g. 0151...)
        if e164.startswith("+49") and len(e164) > 3:
            variants.add("0" + e164[3:])

    # Add simple +/-0 variants for digits-only inputs
    if not base.startswith("+"):
        if base.startswith("0") and len(base) > 1:
            variants.add(base[1:])
        elif not base.startswith("0"):
            variants.add("0" + base)

    # Remove empty strings just in case
    return {v for v in variants if v}


def phone_digits_sequence_regex(digits: str) -> str:
    """
    Build a regex that matches a digit sequence even if non-digits are in between.
    Useful for legacy DB rows that stored phone numbers with spaces/dashes/parentheses.

    Example for digits '5540225177' -> r'5\\D*5\\D*4\\D*0\\D*2\\D*2\\D*5\\D*1\\D*7\\D*7'
    """
    d = re.sub(r"\D", "", str(digits or ""))
    if not d:
        return ""
    return r"\D*".join(list(d))

