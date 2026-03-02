from django.urls import path

from . import views

urlpatterns = [
    path("", views.landing, name="landing"),
    path("m/<slug:restaurant_slug>/", views.public_menu, name="public_menu"),
    path("m/<slug:restaurant_slug>/checkout/", views.checkout, name="checkout"),
    path("auth/login/", views.login_view, name="login"),
    path("auth/register/", views.register_view, name="register"),
    path("panel/", views.panel_dashboard, name="panel_dashboard"),
    path("panel/settings/", views.panel_settings, name="panel_settings"),
    path("panel/categories/", views.panel_categories, name="panel_categories"),
    path("panel/menu-items/", views.panel_menu_items, name="panel_menu_items"),
    path("panel/menu-items/new/", views.panel_menu_item_form, name="panel_menu_item_new"),
    path("panel/menu-items/<int:item_id>/edit/", views.panel_menu_item_form, name="panel_menu_item_edit"),
    path("panel/campaigns/", views.panel_campaigns, name="panel_campaigns"),
]
