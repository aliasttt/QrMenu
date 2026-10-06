from __future__ import annotations

from typing import Any
import logging

from rest_framework.views import exception_handler
from rest_framework_simplejwt.views import TokenRefreshView


logger = logging.getLogger(__name__)


def custom_exception_handler(exc: Exception, context: dict[str, Any]):
    """
    Preserve 401 for subscription status and refresh; keep legacy mapping elsewhere.
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

    view = context.get("view")
    if type(view).__name__ == "AdminSubscriptionView" or isinstance(view, TokenRefreshView):
        response.data.setdefault("code", exc.default_code)
        logger.warning(
            "subscription_auth_failure view=%s code=%s authorization_present=%s bearer_header=%s",
            type(view).__name__, response.data["code"], bool(auth_header), is_bearer,
        )
        return response

    # Only remap when it's clearly an auth-token problem for app flows
    if is_bearer or is_refresh_path:
        response.status_code = 403
        # Keep body as-is; clients only care about status code.
    return response

