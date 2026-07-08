import re
from decimal import Decimal

from django.db import migrations
from django.db.models import Count, Q, Sum


def canonical_phone(phone):
    raw = str(phone or "").strip()
    if not raw:
        return ""
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return ""
    if raw.startswith("00") and len(digits) > 2:
        digits = digits[2:]
    if digits.startswith("49") and len(digits) > 7:
        nsn = digits[2:]
    else:
        nsn = digits
    if nsn.startswith("0"):
        nsn = nsn[1:]
    return f"+49{nsn}" if nsn else ""


def merge_customer_phone_duplicates(apps, schema_editor):
    Customer = apps.get_model("business_menu", "Customer")
    Order = apps.get_model("business_menu", "Order")

    grouped = {}
    for customer in Customer.objects.exclude(phone="").order_by("id"):
        canonical = canonical_phone(customer.phone)
        if not canonical:
            continue
        grouped.setdefault((customer.restaurant_id, canonical), []).append(customer.id)

    for (restaurant_id, canonical), customer_ids in grouped.items():
        primary_id = customer_ids[0]
        Customer.objects.filter(pk=primary_id).update(phone=canonical)
        duplicate_ids = customer_ids[1:]
        if duplicate_ids:
            Order.objects.filter(customer_id__in=duplicate_ids).update(customer_id=primary_id)
            Customer.objects.filter(pk__in=duplicate_ids).delete()

        stats = Order.objects.filter(customer_id=primary_id).aggregate(
            orders_count=Count("id"),
            total_spent=Sum("total_amount", filter=Q(status="paid")),
        )
        last_order = Order.objects.filter(customer_id=primary_id).order_by("-created_at", "-id").first()
        Customer.objects.filter(pk=primary_id).update(
            orders_count=stats.get("orders_count") or 0,
            total_spent=stats.get("total_spent") or Decimal("0.00"),
            last_order_id=last_order.id if last_order else None,
            last_order_at=last_order.created_at if last_order else None,
        )


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("business_menu", "0026_customer_business_profile"),
    ]

    operations = [
        migrations.RunPython(merge_customer_phone_duplicates, migrations.RunPython.noop),

    ]
