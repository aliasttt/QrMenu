"""
Merged: core front (our pages) at / + admin + accounts API + business_menu API and pages.
"""
from django.conf import settings
from django.conf.urls.static import static
from django.conf.urls.i18n import i18n_patterns
from django.contrib import admin
from django.urls import path, include
from rest_framework_simplejwt.views import TokenRefreshView

# Non-translated URLs (APIs, admin, i18n switcher)
urlpatterns = [
    path("i18n/", include("django.conf.urls.i18n")),
    path("admin/", admin.site.urls),
    path("api/business-menu/token/refresh/", TokenRefreshView.as_view(), name="token_refresh_business_menu"),
    path("api/business-menu/refresh/", TokenRefreshView.as_view(), name="token_refresh_business_menu_short"),
    path("api/v1/token/refresh/", TokenRefreshView.as_view(), name="token_refresh_v1"),
    path("api/v1/accounts/", include("accounts.urls")),
    path("api/accounts/", include("accounts.urls")),
    path("api/business-menu/", include("business_menu.urls")),
]

# Translated URLs (frontend pages) — served under /<lang>/... prefix
urlpatterns += i18n_patterns(
    path("", include("core.urls")),
    path("business-menu/", include("business_menu.urls")),
    prefix_default_language=False,
)

handler404 = "core.views.error_404"
handler500 = "core.views.error_500"

urlpatterns += static(settings.MEDIA_URL, document_root=str(settings.MEDIA_ROOT))
