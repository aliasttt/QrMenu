from __future__ import annotations

from datetime import datetime, time

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from business_menu.models import BusinessAdmin, Restaurant
from business_menu.serializers import BusinessMenuSubscriptionSerializer


class Command(BaseCommand):
    help = "Grant an idempotent manual premium entitlement to one BusinessAdmin."

    def add_arguments(self, parser):
        target = parser.add_mutually_exclusive_group(required=True)
        target.add_argument("--admin-id", type=int, help="BusinessAdmin id to update.")
        target.add_argument("--email", help="BusinessAdmin email to update.")
        target.add_argument("--restaurant-id", type=int, help="Restaurant id whose admin should be updated.")
        parser.add_argument(
            "--expires",
            default="2036-12-31",
            help="Entitlement end date in YYYY-MM-DD format. Defaults to 2036-12-31.",
        )
        parser.add_argument(
            "--plan",
            default="manual_pro",
            help="Plan/product marker stored in subscription_product_id.",
        )

    def handle(self, *args, **options):
        admin = self._resolve_admin(options)
        expires_at = self._parse_expiry(options["expires"])
        plan = (options["plan"] or "manual_pro").strip() or "manual_pro"

        with transaction.atomic():
            admin = BusinessAdmin.objects.select_for_update().get(pk=admin.pk)
            admin.payment_status = "paid"
            admin.subscription_ends_at = expires_at
            admin.subscription_provider = "manual"
            admin.subscription_product_id = plan
            admin.subscription_environment = "manual"
            admin.save(
                update_fields=[
                    "payment_status",
                    "subscription_ends_at",
                    "subscription_provider",
                    "subscription_product_id",
                    "subscription_environment",
                ]
            )

        entitlement = BusinessMenuSubscriptionSerializer(admin).data
        restaurant = self._restaurant_for(admin)
        self.stdout.write(self.style.SUCCESS("Manual subscription entitlement granted."))
        self.stdout.write(f"admin_id={admin.id}")
        self.stdout.write(f"email={admin.email or ''}")
        self.stdout.write(f"restaurant_id={restaurant.id if restaurant else ''}")
        self.stdout.write(f"restaurant_name={restaurant.name if restaurant else ''}")
        self.stdout.write(f"state={entitlement['state']}")
        self.stdout.write(f"is_entitled={entitlement['is_entitled']}")
        self.stdout.write(f"provider={entitlement['provider']}")
        self.stdout.write(f"plan={entitlement['plan']}")
        self.stdout.write(f"current_period_end={entitlement['current_period_end']}")
        self.stdout.write(f"purchasable_in_app={entitlement['purchasable_in_app']}")

    def _resolve_admin(self, options):
        if options.get("admin_id"):
            try:
                return BusinessAdmin.objects.get(pk=options["admin_id"])
            except BusinessAdmin.DoesNotExist as exc:
                raise CommandError("No BusinessAdmin found for --admin-id.") from exc

        if options.get("restaurant_id"):
            try:
                return Restaurant.objects.select_related("admin").get(pk=options["restaurant_id"]).admin
            except Restaurant.DoesNotExist as exc:
                raise CommandError("No Restaurant found for --restaurant-id.") from exc

        email = (options.get("email") or "").strip()
        matches = list(BusinessAdmin.objects.filter(email__iexact=email).order_by("id"))
        if not matches:
            raise CommandError("No BusinessAdmin found for --email.")
        if len(matches) > 1:
            ids = ", ".join(str(admin.id) for admin in matches)
            raise CommandError(f"Email matches multiple BusinessAdmins ({ids}); rerun with --admin-id.")
        return matches[0]

    def _parse_expiry(self, value: str):
        try:
            expiry_date = datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError as exc:
            raise CommandError("--expires must use YYYY-MM-DD format.") from exc
        expires_at = timezone.make_aware(datetime.combine(expiry_date, time.max))
        if expires_at <= timezone.now():
            raise CommandError("--expires must be in the future.")
        return expires_at

    def _restaurant_for(self, admin):
        try:
            return admin.restaurant
        except Restaurant.DoesNotExist:
            return None
