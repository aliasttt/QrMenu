"""
Stripe: subscription checkout, webhooks, Connect onboarding.
- Trial: no Stripe. After trial ends, user subscribes via Stripe Checkout.
- After subscription: user can connect Stripe account (Connect) to receive customer payments.
"""
import logging
from django.conf import settings
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import redirect, get_object_or_404, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.utils.decorators import method_decorator
from rest_framework import status, permissions
from rest_framework.views import APIView
from rest_framework.response import Response
from datetime import UTC, datetime, timedelta

from .models import BusinessAdmin, ProviderEvent, ProviderSubscription, Restaurant, Order, Payment
from .subscription_services import apply_provider_event

logger = logging.getLogger(__name__)


def _stripe_enabled():
    return bool(
        getattr(settings, "STRIPE_SECRET_KEY", None)
        and getattr(settings, "STRIPE_PUBLISHABLE_KEY", None)
    )


def _absolute_url(request, path):
    base = (getattr(settings, "SITE_URL", "") or "").rstrip("/")
    if base:
        return f"{base}{path}"
    return request.build_absolute_uri(path)


def _order_belongs_to_session(request, order):
    session_key = request.session.session_key or ""
    return bool(session_key and order.session_key and session_key == order.session_key)


def _record_order_payment_success(order, payment_intent_id, charge_id=""):
    """Persist a verified Stripe success once; the order row serializes duplicate webhooks."""
    if not payment_intent_id:
        return False
    with transaction.atomic():
        locked = Order.objects.select_for_update().get(pk=order.pk)
        locked.status = Order.Status.PAID
        locked.stripe_payment_intent_id = payment_intent_id
        locked.save(update_fields=["status", "stripe_payment_intent_id", "updated_at"])
        payment = Payment.objects.filter(order=locked, stripe_payment_intent_id=payment_intent_id).first()
        if payment is None:
            payment = Payment(order=locked, restaurant=locked.restaurant, stripe_payment_intent_id=payment_intent_id)
        payment.stripe_charge_id = charge_id or payment.stripe_charge_id
        payment.amount = locked.total_amount
        payment.currency = locked.currency or "EUR"
        payment.status = Payment.Status.SUCCEEDED
        payment.save()
    order.refresh_from_db()
    return True


def _verify_checkout_session(order, checkout_session_id):
    """Verify a Checkout Session with Stripe and persist its successful payment."""
    if not checkout_session_id or order.stripe_order_id != checkout_session_id:
        return False
    import stripe
    stripe.api_key = settings.STRIPE_SECRET_KEY
    checkout_session = stripe.checkout.Session.retrieve(checkout_session_id)
    metadata = checkout_session.get("metadata") or {}
    if (
        str(metadata.get("purpose") or "") != "order_payment"
        or str(metadata.get("order_id") or "") != str(order.id)
        or str(metadata.get("restaurant_id") or "") != str(order.restaurant_id)
        or checkout_session.get("payment_status") != "paid"
    ):
        return False
    payment_intent_id = checkout_session.get("payment_intent") or ""
    pi = stripe.PaymentIntent.retrieve(payment_intent_id)
    if pi.get("status") != "succeeded":
        return False
    latest_charge = pi.get("latest_charge")
    return _record_order_payment_success(
        order,
        payment_intent_id,
        latest_charge if isinstance(latest_charge, str) else "",
    )


def _get_subscription_admin(admin_id=None, email=None):
    if admin_id:
        try:
            return BusinessAdmin.objects.get(id=admin_id, is_active=True)
        except (BusinessAdmin.DoesNotExist, ValueError, TypeError):
            return None
    email = (email or "").strip()
    if email:
        return BusinessAdmin.objects.filter(email__iexact=email, is_active=True).order_by("-id").first()
    return None


@method_decorator(csrf_exempt, name="dispatch")
@method_decorator(require_http_methods(["POST"]), name="dispatch")
class StripeWebhookView(APIView):
    """Handle Stripe webhooks: checkout.session.completed, account.updated (Connect)."""
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def post(self, request):
        payload = request.body
        sig_header = request.META.get("HTTP_STRIPE_SIGNATURE", "")
        webhook_secret = getattr(settings, "STRIPE_WEBHOOK_SECRET", None)
        if not webhook_secret:
            logger.warning("STRIPE_WEBHOOK_SECRET not set, skipping signature verification")
            return HttpResponse("Webhook secret not configured", status=500)

        try:
            import stripe
            stripe.api_key = settings.STRIPE_SECRET_KEY
            event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
        except ValueError as e:
            logger.warning("Stripe webhook invalid payload: %s", e)
            return HttpResponse("Invalid payload", status=400)
        except Exception as e:
            logger.warning("Stripe webhook signature error: %s", e)
            return HttpResponse("Invalid signature", status=400)

        if event.type == "checkout.session.completed":
            session = event.data.object
            metadata = session.get("metadata") or {}
            if metadata.get("purpose") == "order_payment":
                order_id = metadata.get("order_id")
                payment_intent_id = session.get("payment_intent") or ""
                if order_id:
                    try:
                        order = Order.objects.get(pk=int(order_id), restaurant_id=int(metadata.get("restaurant_id")))
                        if session.get("payment_status") == "paid":
                            latest_charge = session.get("latest_charge") or ""
                            _record_order_payment_success(order, payment_intent_id, latest_charge)
                        logger.info("Order %s payment confirmed; waiting for customer details", order_id)
                    except (Order.DoesNotExist, ValueError, TypeError):
                        logger.exception("Webhook order not found for checkout session: %s", session.get("id"))
            admin_id = session.get("client_reference_id")
            if admin_id and metadata.get("purpose") != "order_payment":
                try:
                    admin = BusinessAdmin.objects.get(id=int(admin_id))
                    event_id = str(getattr(event, "id", "") or event.get("id") or "").strip()
                    is_live = getattr(event, "livemode", None)
                    if is_live is None:
                        is_live = event.get("livemode")
                    event_environment = "live" if is_live else "test"
                    if ProviderEvent.objects.filter(
                        provider=ProviderSubscription.Provider.STRIPE,
                        environment=event_environment,
                        external_event_id=event_id,
                    ).exists():
                        return HttpResponse("OK", status=200)
                    subscription_ref = session.get("subscription")
                    if isinstance(subscription_ref, dict):
                        stripe_subscription = subscription_ref
                    elif subscription_ref:
                        stripe_subscription = stripe.Subscription.retrieve(subscription_ref)
                    else:
                        raise ValueError("Checkout session is missing its Stripe subscription")
                    stripe_subscription_id = str(stripe_subscription.get("id") or subscription_ref or "").strip()
                    period_end_value = stripe_subscription.get("current_period_end")
                    if not stripe_subscription_id or not period_end_value:
                        raise ValueError("Stripe subscription is missing its ID or current period end")
                    period_end = datetime.fromtimestamp(int(period_end_value), tz=UTC)
                    stripe_status = str(stripe_subscription.get("status") or "unknown")
                    status_map = {
                        "active": ProviderSubscription.Status.ACTIVE,
                        "trialing": ProviderSubscription.Status.TRIALING,
                        "canceled": ProviderSubscription.Status.CANCELED,
                        "unpaid": ProviderSubscription.Status.UNPAID,
                        "past_due": ProviderSubscription.Status.UNPAID,
                    }
                    provider_status = status_map.get(stripe_status, ProviderSubscription.Status.UNKNOWN)
                    cancel_at_period_end = stripe_subscription.get("cancel_at_period_end")
                    will_renew = None if cancel_at_period_end is None else not bool(cancel_at_period_end)
                    event_created = getattr(event, "created", None) or event.get("created")
                    occurred_at = datetime.fromtimestamp(int(event_created), tz=UTC) if event_created else None
                    apply_provider_event(
                        account=admin,
                        provider=ProviderSubscription.Provider.STRIPE,
                        environment=event_environment,
                        external_id=stripe_subscription_id,
                        event_id=event_id,
                        event_type="checkout.session.completed",
                        status=provider_status,
                        current_period_end=period_end,
                        occurred_at=occurred_at,
                        product_id=(getattr(settings, "STRIPE_PRICE_ID_ANNUAL", "") or "").strip(),
                        provider_customer_id=(session.get("customer") or "").strip(),
                        will_renew=will_renew,
                    )
                    admin.stripe_customer_id = (session.get("customer") or "").strip() or None
                    admin.save(update_fields=["stripe_customer_id"])
                    logger.info("Subscription activated for admin_id=%s", admin_id)
                except (BusinessAdmin.DoesNotExist, ValueError, TypeError) as e:
                    logger.exception("Webhook admin not found or invalid client_reference_id: %s", e)
                    return HttpResponse("Subscription event could not be processed", status=500)
                except Exception:
                    logger.exception("Stripe subscription event could not be processed")
                    return HttpResponse("Subscription event could not be processed", status=500)

        elif event.type == "account.updated":
            account = event.data.object
            if account.get("charges_enabled"):
                stripe_account_id = account.get("id")
                if stripe_account_id:
                    updated = BusinessAdmin.objects.filter(stripe_account_id=stripe_account_id).update(
                        stripe_account_id=stripe_account_id
                    )
                    if updated:
                        logger.info("Connect account verified: %s", stripe_account_id)

        elif event.type == "payment_intent.succeeded":
            pi = event.data.object
            order_id = (pi.get("metadata") or {}).get("order_id")
            if order_id:
                try:
                    metadata = pi.get("metadata") or {}
                    order = Order.objects.get(pk=int(order_id), restaurant_id=int(metadata.get("restaurant_id")))
                    latest_charge = pi.get("latest_charge")
                    _record_order_payment_success(
                        order,
                        pi.get("id"),
                        latest_charge if isinstance(latest_charge, str) else "",
                    )
                    logger.info("Order %s payment intent confirmed; waiting for customer details", order_id)
                except (Order.DoesNotExist, ValueError, TypeError):
                    pass

        return HttpResponse("OK", status=200)


class CreateCheckoutSessionView(APIView):
    """Create Stripe Checkout Session for annual subscription. Redirects user to Stripe."""
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        if not _stripe_enabled():
            return Response(
                {"success": False, "message": "Stripe is not configured."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        admin_id = request.data.get("admin_id") or request.query_params.get("admin_id")
        email = request.data.get("email") or request.query_params.get("email")
        if not admin_id and not email:
            return Response(
                {"success": False, "message": "admin_id or email required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        admin = _get_subscription_admin(admin_id=admin_id, email=email)
        if not admin:
            return Response(
                {"success": False, "message": "We could not find an active restaurant account for those details."},
                status=status.HTTP_404_NOT_FOUND,
            )

        price_id = (getattr(settings, "STRIPE_PRICE_ID_ANNUAL", None) or "").strip()
        if not price_id:
            return Response(
                {"success": False, "message": "Subscription price not configured (STRIPE_PRICE_ID_ANNUAL)."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        if price_id.startswith("prod_"):
            return Response(
                {
                    "success": False,
                    "message": "STRIPE_PRICE_ID_ANNUAL must be a Price ID (starts with price_), not a Product ID (prod_). In Stripe Dashboard: Products → your product → copy the Price ID.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        import stripe
        stripe.api_key = settings.STRIPE_SECRET_KEY
        success_url = "https://preismenu.de/payment-success?session_id={CHECKOUT_SESSION_ID}"
        cancel_url = "https://preismenu.de/payment-cancel"

        try:
            session = stripe.checkout.Session.create(
                mode="subscription",
                client_reference_id=str(admin.id),
                customer_email=(admin.email or "").strip() or None,
                line_items=[{"price": price_id, "quantity": 1}],
                automatic_tax={"enabled": True},
                billing_address_collection="required",
                success_url=success_url,
                cancel_url=cancel_url,
            )
            return Response({"success": True, "url": session.url, "session_id": session.id})
        except Exception as e:
            logger.exception("Stripe Checkout create failed: %s", e)
            return Response(
                {"success": False, "message": str(e)},
                status=status.HTTP_502_BAD_GATEWAY,
            )


class RedirectToStripeCheckoutView(APIView):
    """GET with ?admin_id=X: create Checkout Session and redirect to Stripe. On error redirect to subscribe page."""
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        admin_id = request.GET.get("admin_id")
        email = request.GET.get("email")
        if not admin_id and not email:
            return redirect("/business-menu/subscribe/")
        admin = _get_subscription_admin(admin_id=admin_id, email=email)
        if not admin:
            query = f"email={email}" if email else f"admin_id={admin_id}"
            return redirect(f"/business-menu/subscribe/?{query}")
        if not _stripe_enabled():
            return redirect(f"/business-menu/subscribe/?admin_id={admin.id}")
        price_id = (getattr(settings, "STRIPE_PRICE_ID_ANNUAL", None) or "").strip()
        if not price_id or price_id.startswith("prod_"):
            return redirect(f"/business-menu/subscribe/?admin_id={admin.id}")
        import stripe
        stripe.api_key = settings.STRIPE_SECRET_KEY
        success_url = "https://preismenu.de/payment-success?session_id={CHECKOUT_SESSION_ID}"
        cancel_url = "https://preismenu.de/payment-cancel"
        try:
            session = stripe.checkout.Session.create(
                mode="subscription",
                client_reference_id=str(admin.id),
                customer_email=(admin.email or "").strip() or None,
                line_items=[{"price": price_id, "quantity": 1}],
                automatic_tax={"enabled": True},
                billing_address_collection="required",
                success_url=success_url,
                cancel_url=cancel_url,
            )
            if session and getattr(session, "url", None):
                return redirect(session.url)
        except Exception as e:
            logger.exception("RedirectToStripeCheckout failed: %s", e)
        return redirect(f"/business-menu/subscribe/?admin_id={admin.id}")


class CreateConnectAccountLinkView(APIView):
    """Create Stripe Connect Express account (if needed) and Account Link for onboarding. For paid admins only."""
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        if not _stripe_enabled():
            return Response(
                {"success": False, "message": "Stripe is not configured."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        admin_id = request.data.get("admin_id") or request.query_params.get("admin_id")
        if not admin_id:
            return Response(
                {"success": False, "message": "admin_id required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            admin = BusinessAdmin.objects.get(id=admin_id)
        except (BusinessAdmin.DoesNotExist, ValueError):
            return Response(
                {"success": False, "message": "Invalid admin."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if admin.payment_status != "paid":
            return Response(
                {"success": False, "message": "Subscription required before connecting Stripe."},
                status=status.HTTP_403_FORBIDDEN,
            )

        import stripe
        stripe.api_key = settings.STRIPE_SECRET_KEY
        base_url = request.build_absolute_uri("/").rstrip("/")

        try:
            if not admin.stripe_account_id:
                account = stripe.Account.create(type="express", email=(admin.email or "").strip() or None)
                admin.stripe_account_id = account.id
                admin.save(update_fields=["stripe_account_id"])

            link = stripe.AccountLink.create(
                account=admin.stripe_account_id,
                refresh_url=f"{base_url}/business-menu/connect/?admin_id={admin_id}",
                return_url=f"{base_url}/business-menu/connect/done/?admin_id={admin_id}",
                type="account_onboarding",
            )
            return Response({"success": True, "url": link.url})
        except Exception as e:
            logger.exception("Stripe Connect account/link failed: %s", e)
            return Response(
                {"success": False, "message": str(e)},
                status=status.HTTP_502_BAD_GATEWAY,
            )


class ConnectPageView(APIView):
    """GET: create Stripe Connect onboarding link and redirect to Stripe. For paid admins only."""
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        admin_id = request.GET.get("admin_id")
        if not admin_id or not _stripe_enabled():
            return render(request, "business_menu/connect.html", {"error": "Missing admin or Stripe not configured."})
        try:
            admin = BusinessAdmin.objects.get(id=int(admin_id))
        except (ValueError, BusinessAdmin.DoesNotExist):
            return render(request, "business_menu/connect.html", {"error": "Invalid admin."})
        if admin.payment_status != "paid":
            return render(request, "business_menu/connect.html", {"error": "Subscribe first to connect Stripe."})
        import stripe
        stripe.api_key = settings.STRIPE_SECRET_KEY
        base_url = request.build_absolute_uri("/").rstrip("/")
        try:
            if not admin.stripe_account_id:
                account = stripe.Account.create(type="express", email=(admin.email or "").strip() or None)
                admin.stripe_account_id = account.id
                admin.save(update_fields=["stripe_account_id"])
            link = stripe.AccountLink.create(
                account=admin.stripe_account_id,
                refresh_url=f"{base_url}/business-menu/connect/?admin_id={admin_id}",
                return_url=f"{base_url}/business-menu/connect/done/?admin_id={admin_id}",
                type="account_onboarding",
            )
            return redirect(link.url)
        except Exception as e:
            logger.exception("Connect redirect failed: %s", e)
            return render(request, "business_menu/connect.html", {"error": str(e)})


class ConnectDoneView(APIView):
    """Shown after Stripe Connect onboarding return."""
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        admin_id = request.GET.get("admin_id")
        return render(request, "business_menu/connect_done.html", {"admin_id": admin_id})


class SubscribePageView(APIView):
    """Subscribe page: show form and redirect to Stripe Checkout."""
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        admin_id = request.GET.get("admin_id")
        context = {
            "admin_id": admin_id,
            "email": request.GET.get("email", ""),
            "stripe_publishable_key": getattr(settings, "STRIPE_PUBLISHABLE_KEY", ""),
            "subscription_display_price": getattr(settings, "SUBSCRIPTION_DISPLAY_PRICE", "$17.99"),
            "subscription_display_interval": getattr(settings, "SUBSCRIPTION_DISPLAY_INTERVAL", "per month"),
        }
        from django.shortcuts import render
        return render(request, "business_menu/subscribe.html", context)


class SubscribeSuccessView(APIView):
    """After successful Stripe Checkout redirect."""
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        admin_id = request.GET.get("admin_id")
        context = {"admin_id": admin_id}
        from django.shortcuts import render
        return render(request, "business_menu/subscribe_success.html", context)


class SubscribeCancelView(APIView):
    """Shown when the user cancels payment on Stripe Checkout."""
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        admin_id = request.GET.get("admin_id")
        context = {"admin_id": admin_id}
        from django.shortcuts import render
        return render(request, "business_menu/subscribe_cancel.html", context)


class CreateOrderPaymentIntentView(APIView):
    """Create a Stripe PaymentIntent for a customer order. Money goes to restaurant's Connect account."""
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        if not getattr(settings, "STRIPE_SECRET_KEY", None):
            return Response(
                {"success": False, "error": "Stripe is not configured."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        restaurant_id = request.data.get("restaurant_id") or request.query_params.get("restaurant_id")
        order_id = request.data.get("order_id") or request.query_params.get("order_id")
        if not restaurant_id or not order_id:
            return Response(
                {"success": False, "error": "restaurant_id and order_id required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            restaurant = Restaurant.objects.select_related("admin").get(pk=int(restaurant_id), is_active=True)
        except (Restaurant.DoesNotExist, ValueError, TypeError):
            return Response(
                {"success": False, "error": "Restaurant not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        try:
            order = Order.objects.get(pk=int(order_id), restaurant=restaurant)
        except (Order.DoesNotExist, ValueError, TypeError):
            return Response(
                {"success": False, "error": "Order not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        if not _order_belongs_to_session(request, order):
            return Response({"success": False, "error": "Order not found."}, status=status.HTTP_404_NOT_FOUND)
        admin = getattr(restaurant, "admin", None)
        stripe_account_id = getattr(admin, "stripe_account_id", None) if admin else None
        if str(order.payment_method) != "online":
            return Response(
                {"success": False, "error": "This order is not for online payment."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if str(order.status) not in ("pending", "paid"):
            return Response(
                {"success": False, "error": "Order is no longer pending."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        amount_decimal = getattr(order, "total_amount", 0) or 0
        amount_cents = int(round(float(amount_decimal) * 100))
        if amount_cents < 50:
            return Response(
                {"success": False, "error": "Amount too small."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        currency = (getattr(order, "currency", None) or "eur").lower()[:3]
        import stripe
        stripe.api_key = settings.STRIPE_SECRET_KEY
        if order.stripe_payment_intent_id:
            try:
                pi = stripe.PaymentIntent.retrieve(order.stripe_payment_intent_id)
            except Exception as e:
                logger.exception("Existing PaymentIntent retrieve failed: %s", e)
                return Response(
                    {"success": False, "error": "Could not load the existing payment."},
                    status=status.HTTP_502_BAD_GATEWAY,
                )
            return Response({"success": True, "client_secret": pi.client_secret})
        payment_intent_data = {
            "metadata": {"order_id": str(order.id), "restaurant_id": str(restaurant.id)},
        }
        if stripe_account_id:
            payment_intent_data["transfer_data"] = {"destination": stripe_account_id}
        try:
            pi = stripe.PaymentIntent.create(
                amount=amount_cents,
                currency=currency,
                automatic_payment_methods={"enabled": True},
                **payment_intent_data,
            )
        except Exception as e:
            logger.exception("PaymentIntent create failed: %s", e)
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        order.stripe_payment_intent_id = pi.id
        order.save(update_fields=["stripe_payment_intent_id"])
        return Response({
            "success": True,
            "client_secret": pi.client_secret,
        })


class CreateOrderCheckoutSessionView(APIView):
    """Create a Stripe Checkout Session for an order using card or PayPal through Stripe."""
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        if not getattr(settings, "STRIPE_SECRET_KEY", None):
            return Response(
                {"success": False, "error": "Stripe is not configured."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        restaurant_id = request.data.get("restaurant_id") or request.query_params.get("restaurant_id")
        order_id = request.data.get("order_id") or request.query_params.get("order_id")
        provider = (request.data.get("provider") or request.query_params.get("provider") or "stripe").strip().lower()
        if provider not in ("stripe", "paypal"):
            provider = "stripe"
        if not restaurant_id or not order_id:
            return Response(
                {"success": False, "error": "restaurant_id and order_id required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            restaurant = Restaurant.objects.select_related("admin").get(pk=int(restaurant_id), is_active=True)
            order = Order.objects.get(pk=int(order_id), restaurant=restaurant)
        except (Restaurant.DoesNotExist, Order.DoesNotExist, ValueError, TypeError):
            return Response(
                {"success": False, "error": "Order not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        if not _order_belongs_to_session(request, order):
            return Response({"success": False, "error": "Order not found."}, status=status.HTTP_404_NOT_FOUND)

        admin = getattr(restaurant, "admin", None)
        stripe_account_id = getattr(admin, "stripe_account_id", None) if admin else None
        if str(order.payment_method) != "online":
            return Response(
                {"success": False, "error": "This order is not for online payment."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if str(order.status) not in ("pending", "paid"):
            return Response(
                {"success": False, "error": "Order is no longer pending."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        amount_decimal = getattr(order, "total_amount", 0) or 0
        amount_cents = int(round(float(amount_decimal) * 100))
        if amount_cents < 50:
            return Response(
                {"success": False, "error": "Amount too small."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        currency = (getattr(order, "currency", None) or "eur").lower()[:3]
        payment_method_types = ["paypal"] if provider == "paypal" else ["card"]

        import stripe
        stripe.api_key = settings.STRIPE_SECRET_KEY
        if order.stripe_order_id:
            try:
                existing = stripe.checkout.Session.retrieve(order.stripe_order_id)
                if existing.get("status") == "open" and existing.get("url"):
                    return Response({"success": True, "url": existing.get("url"), "session_id": existing.get("id")})
            except Exception:
                logger.info("Existing Checkout Session unavailable for order %s; creating a new one", order.id)
        success_url = _absolute_url(request, f"/restaurants/{restaurant.id}/order/{order.id}/pay/?payment=success&session_id={{CHECKOUT_SESSION_ID}}")
        cancel_url = _absolute_url(request, f"/restaurants/{restaurant.id}/order/{order.id}/pay/?payment=cancel")
        payment_intent_data = {
            "metadata": {
                "purpose": "order_payment",
                "provider": provider,
                "order_id": str(order.id),
                "restaurant_id": str(restaurant.id),
            },
        }
        if stripe_account_id:
            payment_intent_data["transfer_data"] = {"destination": stripe_account_id}
        try:
            session = stripe.checkout.Session.create(
                mode="payment",
                payment_method_types=payment_method_types,
                line_items=[
                    {
                        "price_data": {
                            "currency": currency,
                            "product_data": {
                                "name": f"{restaurant.name} order #{order.id}",
                            },
                            "unit_amount": amount_cents,
                        },
                        "quantity": 1,
                    }
                ],
                payment_intent_data=payment_intent_data,
                metadata={
                    "purpose": "order_payment",
                    "provider": provider,
                    "order_id": str(order.id),
                    "restaurant_id": str(restaurant.id),
                },
                success_url=success_url,
                cancel_url=cancel_url,
            )
        except Exception as e:
            logger.exception("Order Checkout Session create failed: %s", e)
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        order.stripe_order_id = session.id
        order.save(update_fields=["stripe_order_id", "updated_at"])
        return Response({"success": True, "url": session.url, "session_id": session.id})
