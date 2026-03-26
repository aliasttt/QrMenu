from django.urls import path
from django.shortcuts import redirect
from .views import (
    SendOTPView,
    LoginView,
    ForgotPasswordView,
    VerifyResetCodeView,
    ResetPasswordView,
    RestaurantOwnerSignupView,
    UpdateProfileView,
    ChangePasswordView,
    RestaurantProfileView,
    RestaurantProfileLogoUploadView,
    RestaurantProfileGalleryView,
    RestaurantListCreateView,
    MenuItemListCreateView,
    MenuItemCreateFromAppView,
    GetMenuAPIView,
    GenerateQRCodeView,
    SaveMenuFromAppView,
    GetMenuURLView,
    GetQRCodeForAppView,
    ImageUploadView,
    GetImageByUUIDView,
    CloudinaryStatusView,
    CategoryListCreateView,
    CategoryDetailView,
    MenuItemDetailView,
    MenuSetListCreateView,
    MenuSetDetailView,
    PackageListCreateView,
    PackageDetailView,
    MenuThemeListView,
    RestaurantSettingsDetailView,
    OnlineOrderingSettingsView,
    ReservationSettingsView,
    ReservationFloorPlanView,
    CartView,
    RestaurantOrderOptionsView,
    OrderCreateView,
    OrderListView,
    AdminOrderListView,
    AdminOrderNewListView,
    AdminOrderDetailView,
    AdminOrderSettingsView,
    ReservationConfigView,
    ReservationSlotsView,
    ReservationCreateView,
    AdminReservationListView,
    AdminReservationDetailView,
    PaymentPageView,
    menu_qr_display_view,
    menu_qr_image_view,
    menu_themes_preview_view,
)
from .stripe_views import (
    StripeWebhookView,
    CreateCheckoutSessionView,
    RedirectToStripeCheckoutView,
    CreateConnectAccountLinkView,
    CreateOrderPaymentIntentView,
    ConnectPageView,
    ConnectDoneView,
    SubscribePageView,
    SubscribeSuccessView,
    SubscribeCancelView,
)

# app_name removed to avoid namespace conflict
# app_name = 'business_menu'

def redirect_to_service_agreement(request):
    """Redirect old registration page to service agreement"""
    return redirect('/service-agreement/')

urlpatterns = [
    # Restaurant owner signup (web) – starts 12-day trial
    path('signup/', RestaurantOwnerSignupView.as_view(), name='restaurant_owner_signup'),
    # Legacy register redirect
    path('register/', redirect_to_service_agreement, name='restaurant_owner_register'),
    # Payment / subscription page (public)
    path('payment/', PaymentPageView.as_view(), name='payment_page'),
    # Stripe: subscribe (after trial), Connect onboarding
    path('subscribe/', SubscribePageView.as_view(), name='subscribe_page'),
    path('subscribe/checkout/', RedirectToStripeCheckoutView.as_view(), name='subscribe_checkout'),
    path('subscribe/success/', SubscribeSuccessView.as_view(), name='subscribe_success'),
    path('subscribe/cancel/', SubscribeCancelView.as_view(), name='subscribe_cancel'),
    path('connect/', ConnectPageView.as_view(), name='stripe_connect_page'),
    path('connect/done/', ConnectDoneView.as_view(), name='stripe_connect_done'),
    path('api/create-checkout-session/', CreateCheckoutSessionView.as_view(), name='stripe_create_checkout'),
    path('api/create-connect-link/', CreateConnectAccountLinkView.as_view(), name='stripe_connect_link'),
    path('api/create-order-payment-intent/', CreateOrderPaymentIntentView.as_view(), name='stripe_create_order_payment_intent'),
    path('api/stripe-webhook/', StripeWebhookView.as_view(), name='stripe_webhook'),
    # API endpoints
    path('send-otp/', SendOTPView.as_view(), name='send_otp'),
    path('login/', LoginView.as_view(), name='business_menu_login'),
    path('forgot-password/', ForgotPasswordView.as_view(), name='business_menu_forgot_password'),
    path('verify-reset-code/', VerifyResetCodeView.as_view(), name='business_menu_verify_reset_code'),
    path('reset-password/', ResetPasswordView.as_view(), name='business_menu_reset_password'),
    path('update-profile/', UpdateProfileView.as_view(), name='update_profile'),
    path('change-password/', ChangePasswordView.as_view(), name='change_password'),
    path(
        'restaurant-profile/<int:restaurant_id>/',
        RestaurantProfileView.as_view(),
        name='restaurant_profile',
    ),
    path(
        'restaurant-profile/<int:restaurant_id>/upload-logo/',
        RestaurantProfileLogoUploadView.as_view(),
        name='restaurant_profile_upload_logo',
    ),
    path(
        'restaurant-profile/<int:restaurant_id>/gallery/',
        RestaurantProfileGalleryView.as_view(),
        name='restaurant_profile_gallery',
    ),
    path('restaurants/', RestaurantListCreateView.as_view(), name='restaurants'),
    path('menu-items/', MenuItemCreateFromAppView.as_view(), name='menu_items'),
    path('menu-items/<int:pk>/', MenuItemDetailView.as_view(), name='menu_item_detail'),
    path('categories/', CategoryListCreateView.as_view(), name='categories'),
    path('categories/<int:pk>/', CategoryDetailView.as_view(), name='category_detail'),
    path('menu-sets/', MenuSetListCreateView.as_view(), name='menu_sets'),
    path('menu-sets/<int:pk>/', MenuSetDetailView.as_view(), name='menu_set_detail'),
    path('packages/', PackageListCreateView.as_view(), name='packages'),
    path('packages/<int:pk>/', PackageDetailView.as_view(), name='package_detail'),
    path('menu-themes/', MenuThemeListView.as_view(), name='menu_themes'),
    path('restaurant-settings/<int:restaurant_id>/', RestaurantSettingsDetailView.as_view(), name='restaurant_settings'),
    path('online-ordering/<int:restaurant_id>/', OnlineOrderingSettingsView.as_view(), name='online_ordering_settings'),
    path('reservation-settings/<int:restaurant_id>/', ReservationSettingsView.as_view(), name='reservation_settings'),
    path('reservation-settings/<int:restaurant_id>/floor-plan/', ReservationFloorPlanView.as_view(), name='reservation_floor_plan'),
    # سبد و سفارش (عمومی، با token یا restaurant_id)
    path('cart/', CartView.as_view(), name='cart'),
    path('order-options/', RestaurantOrderOptionsView.as_view(), name='order_options'),
    path('orders/', OrderCreateView.as_view(), name='order_create'),
    path('orders/list/', OrderListView.as_view(), name='order_list'),
    path('admin/orders/', AdminOrderListView.as_view(), name='admin_order_list'),
    path('admin/orders/new/', AdminOrderNewListView.as_view(), name='admin_order_new_list'),
    path('admin/orders/<int:order_id>/', AdminOrderDetailView.as_view(), name='admin_order_detail'),
    path('admin/settings/', AdminOrderSettingsView.as_view(), name='admin_order_settings'),
    path('reservation/config/', ReservationConfigView.as_view(), name='reservation_config'),
    path('reservation/slots/', ReservationSlotsView.as_view(), name='reservation_slots'),
    path('reservation/create/', ReservationCreateView.as_view(), name='reservation_create'),
    path('admin/reservations/', AdminReservationListView.as_view(), name='admin_reservation_list'),
    path('admin/reservations/<int:reservation_id>/', AdminReservationDetailView.as_view(), name='admin_reservation_detail'),
    path('get-menu/', GetMenuAPIView.as_view(), name='get_menu'),
    path('generate-qr/', GenerateQRCodeView.as_view(), name='generate_qr'),
    path('save-menu-from-app/', SaveMenuFromAppView.as_view(), name='save_menu_from_app'),
    path('get-menu-url/', GetMenuURLView.as_view(), name='get_menu_url'),
    path('qr-code/', GetQRCodeForAppView.as_view(), name='qr_code_for_app'),
    
    # Image upload and management (Cloudinary with UUID)
    path('upload-image/', ImageUploadView.as_view(), name='upload_image'),
    path('image/<uuid:uuid_str>/', GetImageByUUIDView.as_view(), name='get_image_by_uuid'),
    path('cloudinary-status/', CloudinaryStatusView.as_view(), name='cloudinary_status'),
    
    # QR code display (public)
    path('qr/<str:token>/', menu_qr_display_view, name='menu_qr_display'),
    path('qr/<str:token>.png', menu_qr_image_view, name='menu_qr_image'),
    
    # Theme preview (for testing)
    path('themes/preview/', menu_themes_preview_view, name='menu_themes_preview'),
]

