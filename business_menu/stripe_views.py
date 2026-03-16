"""
Stripe: subscription checkout, webhooks, Connect onboarding.
- Trial: no Stripe. After trial ends, user subscribes via Stripe Checkout.
- After subscription: user can connect Stripe account (Connect) to receive customer payments.
"""
import logging
from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import redirect, get_object_or_404, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.utils.decorators import method_decorator
from rest_framework import status, permissions
from rest_framework.views import APIView
from rest_framework.response import Response
from datetime import timedelta

from .models import BusinessAdmin, Restaurant, Order

logger = logging.getLogger(__name__)


def _stripe_enabled():
    return bool(
        getattr(settings, "STRIPE_SECRET_KEY", None)
        and getattr(settings, "STRIPE_PUBLISHABLE_KEY", None)
    )


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
            admin_id = session.get("client_reference_id")
            if admin_id:
                try:
                    admin = BusinessAdmin.objects.get(id=int(admin_id))
                    admin.payment_status = "paid"
                    admin.subscription_ends_at = timezone.now() + timedelta(days=365)
                    admin.stripe_customer_id = (session.get("customer") or "").strip() or None
                    admin.save(update_fields=["payment_status", "subscription_ends_at", "stripe_customer_id"])
                    logger.info("Subscription activated for admin_id=%s", admin_id)
                except (BusinessAdmin.DoesNotExist, ValueError, TypeError) as e:
                    logger.exception("Webhook admin not found or invalid client_reference_id: %s", e)

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
                    order = Order.objects.get(pk=int(order_id), stripe_payment_intent_id=pi.get("id"))
                    if str(order.status) != "paid":
                        order.status = "paid"
                        order.save(update_fields=["status"])
                        logger.info("Order %s marked paid via PaymentIntent %s", order_id, pi.get("id"))
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
        if not admin_id:
            return redirect("/business-menu/subscribe/")
        try:
            admin = BusinessAdmin.objects.get(id=admin_id)
        except (BusinessAdmin.DoesNotExist, ValueError, TypeError):
            return redirect(f"/business-menu/subscribe/?admin_id={admin_id}")
        if not _stripe_enabled():
            return redirect(f"/business-menu/subscribe/?admin_id={admin_id}")
        price_id = (getattr(settings, "STRIPE_PRICE_ID_ANNUAL", None) or "").strip()
        if not price_id or price_id.startswith("prod_"):
            return redirect(f"/business-menu/subscribe/?admin_id={admin_id}")
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
        return redirect(f"/business-menu/subscribe/?admin_id={admin_id}")


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
        context = {"admin_id": admin_id, "stripe_publishable_key": getattr(settings, "STRIPE_PUBLISHABLE_KEY", "")}
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
        if not _stripe_enabled():
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
        admin = getattr(restaurant, "admin", None)
        if not (admin and getattr(admin, "stripe_account_id", None)):
            return Response(
                {"success": False, "error": "This restaurant does not accept online payment."},
                status=status.HTTP_400_BAD_REQUEST,
            )
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
        try:
            pi = stripe.PaymentIntent.create(
                amount=amount_cents,
                currency=currency,
                automatic_payment_methods={"enabled": True},
                transfer_data={"destination": admin.stripe_account_id},
                metadata={"order_id": str(order.id), "restaurant_id": str(restaurant.id)},
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
