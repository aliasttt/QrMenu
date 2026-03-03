"""
Security middleware for additional protection
"""

from django.utils.deprecation import MiddlewareMixin
from django.conf import settings
import logging

logger = logging.getLogger(__name__)


class SecurityHeadersMiddleware(MiddlewareMixin):
    """
    Add security headers to all responses
    """
    
    def process_response(self, request, response):
        # Security headers (CSP removed - using Django defaults)
        # X-Content-Type-Options
        response['X-Content-Type-Options'] = 'nosniff'
        
        # X-Frame-Options
        response['X-Frame-Options'] = 'DENY'
        
        # X-XSS-Protection
        response['X-XSS-Protection'] = '1; mode=block'
        
        # Referrer-Policy
        response['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        
        # Permissions-Policy (formerly Feature-Policy)
        response['Permissions-Policy'] = (
            'geolocation=(), microphone=(), camera=()'
        )
        
        return response


class IPWhitelistMiddleware(MiddlewareMixin):
    """
    Optional: IP whitelist for admin access
    Only enable if you need to restrict admin access by IP
    """
    
    def process_request(self, request):
        # Only check for admin paths
        if not request.path.startswith('/admin/'):
            return None
        
        # Get whitelist from environment
        whitelist = getattr(settings, 'ADMIN_IP_WHITELIST', [])
        if not whitelist:
            # No whitelist configured, allow all
            return None
        
        # Get client IP
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0].strip()
        else:
            ip = request.META.get('REMOTE_ADDR')
        
        # Check if IP is whitelisted
        if ip not in whitelist:
            logger.warning(f"Blocked admin access attempt from IP: {ip}")
            from django.http import HttpResponseForbidden
            return HttpResponseForbidden("Access denied")
        
        return None


