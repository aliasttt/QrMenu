from __future__ import annotations

from typing import Any

from rest_framework.views import exception_handler


def custom_exception_handler(exc: Exception, context: dict[str, Any]):
    """
    Convert JWT auth failures to 403 (Forbidden) for mobile apps.

    Background:
    - DRF/SimpleJWT normally returns 401 for expired/invalid tokens.
    - Some clients in this project treat ANY 403 as "force logout + go to login".
    - Therefore, when a request includes a Bearer token (or hits token refresh),
      we map 401 -> 403 to match the clients' expectations.
    """
    response = exception_handler(exc, context)
    if response is None:
        return None

    if response.status_code != 401:
        return response

    request = context.get("request")
    auth_header = ""
    path = ""
    try:
        if request is not None:
            auth_header = (request.headers.get("Authorization") or "").strip()
            path = (getattr(request, "path", "") or "").strip()
    except Exception:
        auth_header = ""
        path = ""

    is_bearer = auth_header.lower().startswith("bearer ")
    is_refresh_path = "token/refresh" in (path or "").lower()

    # Only remap when it's clearly an auth-token problem for app flows
    if is_bearer or is_refresh_path:
        response.status_code = 403
        # Keep body as-is; clients only care about status code.
    return response

