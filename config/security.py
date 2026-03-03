"""
Security configurations and utilities
"""

import os
from django.conf import settings


def get_security_settings():
    """
    Get security settings based on environment
    """
    DEBUG = os.environ.get("DJANGO_DEBUG", "0") == "1"
    
    # Security settings
    security_settings = {
        # HTTPS Settings
        'SECURE_SSL_REDIRECT': not DEBUG,
        'SESSION_COOKIE_SECURE': not DEBUG,
        'CSRF_COOKIE_SECURE': not DEBUG,
        'SECURE_HSTS_SECONDS': 31536000 if not DEBUG else 0,  # 1 year in production
        'SECURE_HSTS_INCLUDE_SUBDOMAINS': not DEBUG,
        'SECURE_HSTS_PRELOAD': not DEBUG,
        
        # Security Headers
        'SECURE_CONTENT_TYPE_NOSNIFF': True,
        'SECURE_BROWSER_XSS_FILTER': True,
        'X_FRAME_OPTIONS': 'DENY',
        'SECURE_REFERRER_POLICY': 'strict-origin-when-cross-origin',
        
        # Session Security
        'SESSION_COOKIE_HTTPONLY': True,
        'SESSION_COOKIE_SAMESITE': 'Lax',
        'CSRF_COOKIE_HTTPONLY': True,
        'CSRF_COOKIE_SAMESITE': 'Lax',
        'CSRF_USE_SESSIONS': False,
        'CSRF_COOKIE_NAME': 'csrftoken',
        
        # Other Security
        'SECURE_PROXY_SSL_HEADER': ('HTTP_X_FORWARDED_PROTO', 'https'),
    }
    
    return security_settings

