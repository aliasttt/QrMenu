"""
PDF invoice generation + customer confirmation email.
Triggered when an order reaches the invoice-ready stage:
  - cash orders: right after the order is created,
  - online orders: right after payment finalization.
"""
from __future__ import annotations

import io
import logging
from decimal import Decimal

from django.conf import settings
from django.core.mail import EmailMessage, get_connection

logger = logging.getLogger(__name__)


def _fmt_money(value, currency: str) -> str:
    try:
        d = Decimal(str(value)).quantize(Decimal("0.01"))
    except Exception:
        d = Decimal("0.00")
    return f"{currency} {d}"


def build_invoice_pdf(order) -> bytes:
    """Render a simple, self-contained PDF invoice for the given Order."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    )

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=18 * mm, bottomMargin=18 * mm,
        title=f"Invoice #{order.id}",
    )
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontSize=20, spaceAfter=4)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=12, spaceAfter=4)
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=9, textColor=colors.grey)
    normal = styles["Normal"]

    restaurant = getattr(order, "restaurant", None)
    customer = getattr(order, "customer", None)
    currency = order.currency or "EUR"
    created = order.updated_at or order.created_at

    elements = []
    elements.append(Paragraph(f"Invoice #{order.id}", h1))
    elements.append(Paragraph(
        (restaurant.name if restaurant else "") + (" &nbsp;·&nbsp; " + created.strftime("%Y-%m-%d %H:%M") if created else ""),
        small,
    ))
    elements.append(Spacer(1, 8))

    # Parties block
    seller = [
        Paragraph("<b>Seller</b>", h2),
        Paragraph(restaurant.name if restaurant else "-", normal),
    ]
    if restaurant and getattr(restaurant, "address", ""):
        seller.append(Paragraph(restaurant.address, normal))
    if restaurant and getattr(restaurant, "phone", ""):
        seller.append(Paragraph(f"Phone: {restaurant.phone}", normal))
    if restaurant and getattr(restaurant, "email", ""):
        seller.append(Paragraph(f"Email: {restaurant.email}", normal))

    buyer = [
        Paragraph("<b>Customer</b>", h2),
        Paragraph((customer.name if customer else "") or "-", normal),
    ]
    if customer:
        if customer.phone:
            buyer.append(Paragraph(f"Phone: {customer.phone}", normal))
        if customer.email:
            buyer.append(Paragraph(f"Email: {customer.email}", normal))
        if customer.address:
            buyer.append(Paragraph(customer.address, normal))

    parties = Table([[seller, buyer]], colWidths=[85 * mm, 85 * mm])
    parties.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    elements.append(parties)
    elements.append(Spacer(1, 12))

    # Meta
    meta_rows = [
        ["Status", str(order.status).capitalize()],
        ["Service", str(order.service_type).replace("_", " ").capitalize()],
        ["Payment", str(order.payment_method).capitalize()],
    ]
    if order.table_number:
        meta_rows.append(["Table", str(order.table_number)])
    meta = Table(meta_rows, colWidths=[35 * mm, 135 * mm])
    meta.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
    ]))
    elements.append(meta)
    elements.append(Spacer(1, 10))

    # Items
    header = ["#", "Item", "Qty", "Unit price", "Line total"]
    rows = [header]
    total = Decimal("0.00")
    for i, item in enumerate(order.items_json or [], start=1):
        name = str(item.get("name") or "-")
        try:
            qty = int(item.get("quantity") or 1)
        except Exception:
            qty = 1
        try:
            price = Decimal(str(item.get("price") or "0").replace(",", "."))
        except Exception:
            price = Decimal("0.00")
        line = (price * qty).quantize(Decimal("0.01"))
        total += line
        rows.append([str(i), name, str(qty), _fmt_money(price, currency), _fmt_money(line, currency)])

    rows.append(["", "", "", "Total", _fmt_money(order.total_amount or total, currency)])

    tbl = Table(rows, colWidths=[10 * mm, 80 * mm, 15 * mm, 30 * mm, 35 * mm], repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#111827")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#F8FAFC")]),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.HexColor("#111827")),
        ("LINEABOVE", (0, -1), (-1, -1), 0.75, colors.HexColor("#111827")),
        ("FONTNAME", (3, -1), (-1, -1), "Helvetica-Bold"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
    ]))
    elements.append(tbl)
    elements.append(Spacer(1, 14))

    elements.append(Paragraph(
        "Thank you for your order. This document serves as a purchase confirmation.",
        small,
    ))

    doc.build(elements)
    return buf.getvalue()


def _customer_email_for(order) -> str:
    customer = getattr(order, "customer", None)
    email = (customer.email if customer else "") or ""
    return email.strip()


def _resolve_from_email() -> str:
    """
    Choose a sender address that the configured SMTP will actually accept.
    Priority: BONUS_FROM_EMAIL → DEFAULT_FROM_EMAIL (if it looks real) →
    EMAIL_HOST_USER (last resort, because titan/smtp servers reject FROM
    addresses that don't match an authenticated mailbox on the account).
    """
    for attr in ("BONUS_FROM_EMAIL", "DEFAULT_FROM_EMAIL"):
        v = getattr(settings, attr, None)
        if v and "@" in v and "example.com" not in v.lower():
            return v
    host_user = getattr(settings, "BONUS_EMAIL_HOST_USER", getattr(settings, "EMAIL_HOST_USER", "")) or ""
    if host_user and "@" in host_user:
        return host_user
    # Absolute last resort — will likely fail but keeps behaviour explicit.
    return getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@example.com")


def send_invoice_email(order) -> bool:
    """
    Send a confirmation email to the customer with the invoice PDF attached.
    Best-effort: returns True on success, False on failure — never raises.
    """
    try:
        to_email = _customer_email_for(order)
        if not to_email:
            logger.warning(
                "Invoice email skipped for order %s: no customer email on Customer(id=%s)",
                order.id,
                getattr(getattr(order, "customer", None), "id", None),
            )
            return False

        try:
            pdf_bytes = build_invoice_pdf(order)
        except Exception:
            logger.exception("Invoice PDF build failed for order %s", order.id)
            pdf_bytes = None

        restaurant = getattr(order, "restaurant", None)
        currency = order.currency or "EUR"
        subject = f"Order #{order.id} confirmed — {restaurant.name if restaurant else 'your order'}"
        customer_name = getattr(getattr(order, "customer", None), "name", "") or ""
        greeting = f"Hi {customer_name.split()[0]}," if customer_name else "Hi,"
        tracking_url = ""
        try:
            if restaurant:
                base = getattr(settings, "PUBLIC_BASE_URL", "") or ""
                tracking_url = f"{base}/restaurants/{restaurant.id}/orders/"
        except Exception:
            tracking_url = ""

        body_lines = [
            greeting,
            "",
            f"Your order #{order.id} has been confirmed.",
            f"Total: {currency} {order.total_amount}",
            f"Service: {str(order.service_type).replace('_', ' ')}",
            f"Payment: {order.payment_method}",
        ]
        if tracking_url:
            body_lines += ["", f"Track your order: {tracking_url}"]
        body_lines += [
            "",
            "The invoice for this order is attached as a PDF.",
            "",
            f"— {restaurant.name if restaurant else 'The team'}",
        ]
        body = "\n".join(body_lines)

        from_email = _resolve_from_email()
        host = getattr(settings, "BONUS_EMAIL_HOST", settings.EMAIL_HOST)
        port = getattr(settings, "BONUS_EMAIL_PORT", getattr(settings, "EMAIL_PORT", 587))
        user = getattr(settings, "BONUS_EMAIL_HOST_USER", getattr(settings, "EMAIL_HOST_USER", ""))
        password = getattr(settings, "BONUS_EMAIL_HOST_PASSWORD", getattr(settings, "EMAIL_HOST_PASSWORD", ""))
        use_tls = getattr(settings, "BONUS_EMAIL_USE_TLS", getattr(settings, "EMAIL_USE_TLS", True))
        logger.info(
            "Sending invoice email order=%s to=%s from=%s host=%s port=%s user=%s attach=%s",
            order.id, to_email, from_email, host, port, bool(user), bool(pdf_bytes),
        )
        connection = get_connection(
            backend="django.core.mail.backends.smtp.EmailBackend",
            host=host, port=port, username=user, password=password,
            use_tls=use_tls, timeout=30,
        )
        msg = EmailMessage(
            subject=subject,
            body=body,
            from_email=from_email,
            to=[to_email],
            connection=connection,
        )
        if pdf_bytes:
            msg.attach(f"invoice-{order.id}.pdf", pdf_bytes, "application/pdf")
        sent = msg.send(fail_silently=False)
        logger.info("Invoice email send() returned %s for order %s → %s", sent, order.id, to_email)
        return bool(sent)
    except Exception:
        logger.exception("Invoice email failed for order %s", getattr(order, "id", "?"))
        return False


def send_invoice_email_async(order_id: int) -> None:
    """
    Reload the order and send the email. Intended to be wired via
    `transaction.on_commit(lambda: send_invoice_email_async(order.id))`
    so we send only after the DB commit succeeds.
    """
    try:
        from .models import Order
        order = Order.objects.select_related("restaurant", "customer").get(pk=order_id)
        send_invoice_email(order)
    except Exception:
        logger.exception("send_invoice_email_async failed for order %s", order_id)
