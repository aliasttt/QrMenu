from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from business_menu.models import ProviderSubscription
from business_menu.subscription_services import (
    SubscriptionVerificationError,
    acknowledge_google_play_subscription,
    decrypt_google_purchase_token,
    verify_google_play_subscription,
)


class Command(BaseCommand):
    help = "Retry pending Google Play acknowledgements; dry-run unless --apply is supplied."
    advisory_lock_id = 7185213762351

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--limit", type=int, default=100)

    def handle(self, *args, **options):
        locked = False
        if options["apply"] and connection.vendor == "postgresql":
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_try_advisory_lock(%s)", [self.advisory_lock_id])
                locked = cursor.fetchone()[0]
            if not locked:
                self.stdout.write("mode=SKIP reason=already_running")
                return

        try:
            self._run(options)
        finally:
            if locked:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_advisory_unlock(%s)", [self.advisory_lock_id])

    def _run(self, options):
        rows = list(
            ProviderSubscription.objects.filter(
                provider=ProviderSubscription.Provider.GOOGLE,
                needs_reconciliation=True,
            ).order_by("updated_at")[: max(1, options["limit"])]
        )
        if not options["apply"]:
            self.stdout.write(f"mode=DRY-RUN pending={len(rows)}")
            return

        acknowledged = skipped = failed = 0
        for row in rows:
            try:
                token = decrypt_google_purchase_token(row.provider_customer_id)
                result = verify_google_play_subscription(token)
                if acknowledge_google_play_subscription(result) or not result.acknowledgement_pending:
                    row.needs_reconciliation = False
                    row.save(update_fields=["needs_reconciliation", "updated_at"])
                    acknowledged += 1
                else:
                    skipped += 1
            except SubscriptionVerificationError:
                failed += 1
        self.stdout.write(
            f"mode=APPLY examined={len(rows)} acknowledged={acknowledged} skipped={skipped} failed={failed}"
        )
        if failed:
            raise CommandError(f"{failed} Google Play acknowledgement(s) remain pending")
