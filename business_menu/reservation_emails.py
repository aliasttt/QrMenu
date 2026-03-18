"""Emails for reservation: new request (to owner), confirmed (to customer), cancelled (to customer)."""
import logging
from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


def _from_email():
    return getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@preismenu.de")


def send_reservation_new_request_email(reservation):
    """Notify restaurant owner of a new reservation request (optional; can be used for in-app only)."""
    try:
        restaurant = reservation.restaurant
        admin = getattr(restaurant, "admin", None)
        if not admin or not (getattr(admin, "email", None) or "").strip():
            return
        to = (admin.email or "").strip()
        subject = f"[Reservation] New request for {restaurant.name} – {reservation.requested_date} {reservation.requested_time}"
        lines = [
            f"A new reservation request has been received.",
            "",
            f"Date: {reservation.requested_date}",
            f"Time: {reservation.requested_time}",
            f"Guests: {reservation.guests_count}",
            f"Name: {reservation.customer_name}",
            f"Phone: {reservation.customer_phone or '—'}",
            f"Email: {reservation.customer_email or '—'}",
            f"Notes: {reservation.notes or '—'}",
        ]
        if reservation.order_details_json:
            lines.append("")
            lines.append("Order (pre-order):")
            for item in reservation.order_details_json:
                name = item.get("name", "")
                qty = item.get("quantity", 1)
                price = item.get("price", "0")
                lines.append(f"  – {qty}× {name} @ €{price}")
        lines.append("")
        lines.append("Please approve or cancel this reservation from your app/panel.")
        message = "\n".join(lines)
        send_mail(
            subject=subject,
            message=message,
            from_email=_from_email(),
            recipient_list=[to],
            fail_silently=True,
        )
    except Exception as e:
        logger.warning("Reservation new-request email failed: %s", e)


def send_reservation_confirmation_email(reservation):
    """Send confirmation to customer when owner approves the reservation."""
    email = (reservation.customer_email or "").strip()
    if not email:
        return
    try:
        restaurant = reservation.restaurant
        subject = f"Reservation confirmed – {restaurant.name}"
        lines = [
            f"Hello {reservation.customer_name},",
            "",
            f"Your reservation at {restaurant.name} has been confirmed.",
            "",
            f"Date: {reservation.requested_date}",
            f"Time: {reservation.requested_time}",
            f"Guests: {reservation.guests_count}",
            "",
            f"Restaurant: {restaurant.name}",
            f"Address: {restaurant.address or '—'}",
            f"Phone: {restaurant.phone or getattr(restaurant.admin, 'phone', '—')}",
            "",
            "We look forward to seeing you.",
        ]
        if reservation.order_details_json:
            lines.append("")
            lines.append("Your pre-order:")
            for item in reservation.order_details_json:
                name = item.get("name", "")
                qty = item.get("quantity", 1)
                price = item.get("price", "0")
                lines.append(f"  – {qty}× {name} @ €{price}")
        message = "\n".join(lines)
        send_mail(
            subject=subject,
            message=message,
            from_email=_from_email(),
            recipient_list=[email],
            fail_silently=True,
        )
    except Exception as e:
        logger.warning("Reservation confirmation email failed: %s", e)


def send_reservation_cancelled_email(reservation, reason=None):
    """Send cancellation notice to customer when owner cancels (refund handled separately)."""
    email = (reservation.customer_email or "").strip()
    if not email:
        return
    try:
        restaurant = reservation.restaurant
        subject = f"Reservation cancelled – {restaurant.name}"
        lines = [
            f"Hello {reservation.customer_name},",
            "",
            f"Your reservation at {restaurant.name} for {reservation.requested_date} at {reservation.requested_time} has been cancelled.",
            "",
        ]
        if reason:
            lines.append(f"Reason: {reason}")
            lines.append("")
        lines.append("If you had paid online, your payment will be refunded to your original payment method.")
        lines.append("")
        lines.append("You can make a new reservation at any time.")
        message = "\n".join(lines)
        send_mail(
            subject=subject,
            message=message,
            from_email=_from_email(),
            recipient_list=[email],
            fail_silently=True,
        )
    except Exception as e:
        logger.warning("Reservation cancelled email failed: %s", e)
