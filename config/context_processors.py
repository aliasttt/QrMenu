from __future__ import annotations

from django.conf import settings


def firebase_settings(request):
    """
    Expose Firebase config and VAPID key to templates without hardcoding secrets.

    Only non-sensitive values should be passed here.
    """
    return {
        "FIREBASE_PUBLIC_CONFIG": getattr(settings, "FIREBASE_CONFIG", {}),
        "VAPID_PUBLIC_KEY": getattr(settings, "VAPID_PUBLIC_KEY", ""),
    }

