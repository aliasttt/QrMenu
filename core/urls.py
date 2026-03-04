from django.urls import path

from . import views

urlpatterns = [
    path("", views.landing, name="landing"),
    path("features/", views.features, name="features"),
    path("how-it-works/", views.how_it_works, name="how_it_works"),
    path("pricing/", views.pricing, name="pricing"),
    path("contact/", views.contact, name="contact"),
    path("restaurants/", views.restaurants_list, name="restaurants_list"),
    path("restaurants/<int:restaurant_id>/menu/", views.restaurant_menu, name="restaurant_menu"),
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
