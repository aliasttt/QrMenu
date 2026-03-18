from django.urls import path

from . import views

urlpatterns = [
    path("", views.landing, name="landing"),
    path("features/", views.features, name="features"),
    path("how-it-works/", views.how_it_works, name="how_it_works"),
    path("pricing/", views.pricing, name="pricing"),
    path("services/", views.services, name="services"),
    path("services/<slug:service_slug>/", views.service_detail, name="service_detail"),
    path("contact/", views.contact, name="contact"),
    path("restaurants/", views.restaurants_list, name="restaurants_list"),
    path("restaurants/<int:restaurant_id>/menu/", views.restaurant_menu, name="restaurant_menu"),
    path("restaurants/<int:restaurant_id>/schedule/", views.restaurant_schedule, name="restaurant_schedule"),
    path("restaurants/<int:restaurant_id>/reservation/", views.restaurant_reservation, name="restaurant_reservation"),
    path("restaurants/<int:restaurant_id>/order/<int:order_id>/pay/", views.order_payment, name="order_payment"),
    path("m/<slug:restaurant_slug>/", views.public_menu, name="public_menu"),
    path("m/<slug:restaurant_slug>/checkout/", views.checkout, name="checkout"),
    path("auth/login/", views.login_view, name="login"),
    path("auth/logout/", views.logout_view, name="logout"),
    path("auth/forgot-password/", views.forgot_password_view, name="forgot_password"),
    path("auth/register/", views.register_view, name="register"),
    path("payment-success/", views.payment_success_view, name="payment_success"),
    path("payment-cancel/", views.payment_cancel_view, name="payment_cancel"),
    path("panel/", views.panel_dashboard, name="panel_dashboard"),
    path("panel/settings/", views.panel_settings, name="panel_settings"),
    path("panel/categories/", views.panel_categories, name="panel_categories"),
    path("panel/menu-items/", views.panel_menu_items, name="panel_menu_items"),
    path("panel/menu-items/new/", views.panel_menu_item_form, name="panel_menu_item_new"),
    path("panel/menu-items/<int:item_id>/edit/", views.panel_menu_item_form, name="panel_menu_item_edit"),
    path("panel/campaigns/", views.panel_campaigns, name="panel_campaigns"),
]
