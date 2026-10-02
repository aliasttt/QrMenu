from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from business_menu.models import BusinessAdmin, ProviderSubscription
from business_menu.subscription_services import canonical_environment


class Command(BaseCommand):
    help = "Dry-run by default; optionally backfill legacy billing fields without claiming store verification."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write idempotent legacy rows. Without this flag no data is changed.",
        )

    def handle(self, *args, **options):
        apply_changes = bool(options["apply"])
        counts = {"candidate": 0, "created": 0, "updated": 0, "skipped": 0, "reconciliation": 0}
        now = timezone.now()

        for admin in BusinessAdmin.objects.order_by("id").iterator():
            has_subscription_shape = bool(
                admin.payment_status == "paid"
                or admin.subscription_provider
                or admin.subscription_product_id
                or admin.subscription_original_transaction_id
                or admin.subscription_transaction_id
                or admin.subscription_ends_at
            )
            if not has_subscription_shape:
                continue
            counts["candidate"] += 1

            provider = (admin.subscription_provider or "legacy").strip().lower()
            if provider not in ProviderSubscription.Provider.values:
                provider = ProviderSubscription.Provider.LEGACY
            environment = canonical_environment(provider, admin.subscription_environment or "legacy")
            stable_id = ""
            if provider == ProviderSubscription.Provider.APPLE:
                stable_id = (admin.subscription_original_transaction_id or "").strip()
                if stable_id and BusinessAdmin.objects.exclude(pk=admin.pk).filter(
                    subscription_original_transaction_id=stable_id
                ).exists():
                    provider = ProviderSubscription.Provider.LEGACY
                    environment = "legacy"
                    stable_id = ""
            elif provider == ProviderSubscription.Provider.MANUAL:
                stable_id = f"manual:{admin.id}"
            if not stable_id:
                stable_id = f"legacy-admin:{admin.id}"

            if admin.payment_status == "paid" and admin.subscription_ends_at and admin.subscription_ends_at > now:
                subscription_status = ProviderSubscription.Status.ACTIVE
            elif admin.subscription_ends_at and admin.subscription_ends_at <= now:
                subscription_status = ProviderSubscription.Status.EXPIRED
            else:
                subscription_status = ProviderSubscription.Status.UNKNOWN

            is_manual = provider == ProviderSubscription.Provider.MANUAL
            source = (
                ProviderSubscription.VerificationSource.MANUAL
                if is_manual
                else ProviderSubscription.VerificationSource.LEGACY
            )
            needs_reconciliation = not is_manual
            latest_transaction_id = (admin.subscription_transaction_id or "").strip()
            if latest_transaction_id and BusinessAdmin.objects.exclude(pk=admin.pk).filter(
                subscription_transaction_id=latest_transaction_id
            ).exists():
                latest_transaction_id = ""
                needs_reconciliation = True
            counts["reconciliation"] += int(needs_reconciliation)
            if not apply_changes:
                continue

            with transaction.atomic():
                existing = ProviderSubscription.objects.select_for_update().filter(
                    provider=provider,
                    environment=environment,
                    external_id=stable_id,
                ).first()
                if existing and existing.verification_source != ProviderSubscription.VerificationSource.LEGACY:
                    counts["skipped"] += 1
                    continue
                if existing and existing.account_id != admin.id:
                    counts["skipped"] += 1
                    continue
                _row, created = ProviderSubscription.objects.update_or_create(
                    provider=provider,
                    environment=environment,
                    external_id=stable_id,
                    defaults={
                        "account": admin,
                        "latest_transaction_id": latest_transaction_id,
                        "provider_customer_id": (admin.stripe_customer_id or "").strip(),
                        "product_id": (admin.subscription_product_id or "").strip(),
                        "status": subscription_status,
                        "current_period_end": admin.subscription_ends_at,
                        "will_renew": None,
                        "verification_source": source,
                        "needs_reconciliation": needs_reconciliation,
                    },
                )
                counts["created" if created else "updated"] += 1

        mode = "APPLY" if apply_changes else "DRY-RUN"
        self.stdout.write(f"mode={mode}")
        for key in ("candidate", "created", "updated", "skipped", "reconciliation"):
            self.stdout.write(f"{key}={counts[key]}")
