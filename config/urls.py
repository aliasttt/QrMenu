"""
Merged: core front (our pages) at / + admin + accounts API + business_menu API and pages.
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, include
from rest_framework_simplejwt.views import TokenRefreshView

urlpatterns = [
    # Our front pages (landing, menu, panel, etc.) – keep style
    path("", include("core.urls")),
    path("admin/", admin.site.urls),
    # JWT refresh for business_menu (OTP login)
    path("api/business-menu/token/refresh/", TokenRefreshView.as_view(), name="token_refresh_business_menu"),
    path("api/business-menu/refresh/", TokenRefreshView.as_view(), name="token_refresh_business_menu_short"),
    path("api/v1/token/refresh/", TokenRefreshView.as_view(), name="token_refresh_v1"),
    # Accounts (OTP, login, register)
    path("api/v1/accounts/", include("accounts.urls")),
    path("api/accounts/", include("accounts.urls")),
    # Business Menu API + public QR menu pages
    path("api/business-menu/", include("business_menu.urls")),
    path("business-menu/", include("business_menu.urls")),
]

handler404 = "core.views.error_404"
handler500 = "core.views.error_500"

urlpatterns += static(settings.MEDIA_URL, document_root=str(settings.MEDIA_ROOT))
