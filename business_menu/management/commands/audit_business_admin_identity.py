import json
from collections import defaultdict

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand

from business_menu.identity import normalize_business_email, normalize_business_phone
from business_menu.models import BusinessAdmin, Restaurant
from business_menu.subscription_services import resolve_subscription_entitlement


class Command(BaseCommand):
    help = "Dry-run audit of BusinessAdmin identity conflicts; never changes data or prints contact details."

    def handle(self, *args, **options):
        rows = list(BusinessAdmin.objects.select_related("auth_user").prefetch_related("restaurant").all())
        email_groups = defaultdict(list)
        phone_groups = defaultdict(list)
        invalid_emails = []
        invalid_phones = []
        records = []

        for admin in rows:
            try:
                email_groups[normalize_business_email(admin.email)].append(admin.pk)
            except (ValidationError, ValueError, TypeError):
                invalid_emails.append(admin.pk)
            try:
                phone_groups[normalize_business_phone(admin.phone)].append(admin.pk)
            except (ValidationError, ValueError, TypeError):
                invalid_phones.append(admin.pk)

            try:
                restaurant_id = admin.restaurant.pk
            except Restaurant.DoesNotExist:
                restaurant_id = None
            try:
                subscription = resolve_subscription_entitlement(admin)
                subscription_state = subscription.get("state", "unknown")
            except Exception:
                subscription_state = "unavailable"
            records.append({
                "business_admin_id": admin.pk,
                "auth_user_id": admin.auth_user_id,
                "auth_user_is_active": admin.auth_user.is_active if admin.auth_user_id else None,
                "restaurant_id": restaurant_id,
                "restaurant_is_active": admin.restaurant.is_active if restaurant_id else None,
                "subscription_state": subscription_state,
            })

        duplicate_emails = [ids for ids in email_groups.values() if len(ids) > 1]
        duplicate_phones = [ids for ids in phone_groups.values() if len(ids) > 1]
        records_by_admin = {item["business_admin_id"]: item for item in records}
        incomplete_links = []
        for row in rows:
            record = records_by_admin[row.pk]
            restaurant_id = record["restaurant_id"]
            reasons = []
            if not row.auth_user_id:
                reasons.append("missing_auth_user")
            elif not row.auth_user.is_active:
                reasons.append("inactive_auth_user")
            else:
                try:
                    profile = row.auth_user.profile
                except Exception:
                    profile = None
                if not profile:
                    reasons.append("missing_profile")
                elif not profile.is_active:
                    reasons.append("inactive_profile")
                if row.auth_user.email.strip().lower() != row.email:
                    reasons.append("auth_user_email_mismatch")
                if profile and profile.phone != row.phone:
                    reasons.append("profile_phone_mismatch")
            if not restaurant_id:
                reasons.append("missing_restaurant")
            elif not record["restaurant_is_active"]:
                reasons.append("inactive_restaurant")
            if reasons:
                incomplete_links.append({
                    "business_admin_id": row.pk,
                    "auth_user_id": row.auth_user_id,
                    "restaurant_id": restaurant_id,
                    "reasons": reasons,
                })
        report = {
            "mode": "dry-run",
            "business_admin_count": len(rows),
            "duplicate_email_groups": duplicate_emails,
            "duplicate_phone_groups": duplicate_phones,
            "empty_or_invalid_email_business_admin_ids": invalid_emails,
            "ambiguous_or_invalid_phone_business_admin_ids": invalid_phones,
            "incomplete_links": incomplete_links,
            "accounts": records,
        }
        self.stdout.write(json.dumps(report, sort_keys=True))
