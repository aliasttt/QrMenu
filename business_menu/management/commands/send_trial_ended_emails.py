"""
Mark trial as ended and send email to restaurant owners.
Run daily via cron: python manage.py send_trial_ended_emails
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.core.mail import send_mail
from django.conf import settings

from business_menu.models import BusinessAdmin


class Command(BaseCommand):
    help = "Set payment_status to unpaid for expired trials and send trial-ended email"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Only list, do not update or send")

    def handle(self, *args, **options):
        now = timezone.now()
        qs = BusinessAdmin.objects.filter(
            payment_status="trial",
            trial_ends_at__lte=now,
            trial_ends_at__isnull=False,
        )
        dry_run = options.get("dry_run", False)
        count = 0
        for admin in qs:
            email = (admin.email or "").strip()
            if not email:
                self.stdout.write(self.style.WARNING(f"Admin id={admin.id} has no email, skipping"))
                continue
            if dry_run:
                self.stdout.write(f"Would mark trial ended and email: {email} (id={admin.id})")
            else:
                admin.payment_status = "unpaid"
                admin.save(update_fields=["payment_status"])
                base_url = getattr(settings, "SITE_URL", "https://preismenu.de").rstrip("/")
                subscribe_url = f"{base_url}/business-menu/subscribe/?admin_id={admin.id}"
                send_mail(
                    subject="Your free trial has ended – subscribe to continue",
                    message=f"""Hello {admin.name},

Your 12-day free trial has ended.

To continue using the service (orders, menu, app), please subscribe here:
{subscribe_url}

If you have any questions, contact support.

Best regards,
QR Menu Team
""",
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[email],
                    fail_silently=True,
                )
                self.stdout.write(self.style.SUCCESS(f"Marked trial ended and emailed: {email}"))
            count += 1
        self.stdout.write(f"Processed {count} expired trial(s).")
