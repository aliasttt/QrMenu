from django.middleware.common import CommonMiddleware
from django.db import connection
from django.utils.deprecation import MiddlewareMixin
import time


class APIAppendSlashMiddleware(CommonMiddleware):
    """
    Middleware to disable APPEND_SLASH behavior for API routes.
    This prevents 500 errors when POST requests are made to URLs without trailing slashes.
    """
    
    def process_response(self, request, response):
        # Skip APPEND_SLASH redirect for API routes, especially for POST/PUT/PATCH/DELETE
        if request.path.startswith('/api/'):
            # For API routes, don't redirect even if URL doesn't have trailing slash
            # This prevents RuntimeError for POST requests
            return response
        
        # For non-API routes, use default CommonMiddleware behavior
        return super().process_response(request, response)


class AdminLogSequenceGuardMiddleware(MiddlewareMixin):
    """
    Prevent PostgreSQL duplicate-key crashes on django_admin_log after DB imports.
    On admin POST requests, re-sync the log table id sequence to current MAX(id).
    """

    _last_sync_ts = 0.0
    _sync_interval_seconds = 10.0

    @classmethod
    def _sync_admin_log_sequence(cls):
        if connection.vendor != "postgresql":
            return
        now = time.monotonic()
        if (now - cls._last_sync_ts) < cls._sync_interval_seconds:
            return
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT setval(
                    pg_get_serial_sequence('django_admin_log', 'id'),
                    COALESCE((SELECT MAX(id) FROM django_admin_log), 0) + 1,
                    false
                )
                """
            )
        cls._last_sync_ts = now

    def process_request(self, request):
        if request.method != "POST":
            return None
        if not request.path.startswith("/admin/"):
            return None
        try:
            self._sync_admin_log_sequence()
        except Exception:
            # Never block admin request on guard failures.
            return None
        return None

