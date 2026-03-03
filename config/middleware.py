from django.middleware.common import CommonMiddleware


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

