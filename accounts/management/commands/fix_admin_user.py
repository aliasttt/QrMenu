"""
Set a user as staff + superuser and optionally set password (for Django admin login).
Usage:
  python manage.py fix_admin_user --username qrmenu --password 'Tek1212='
  python manage.py fix_admin_user --username qrmenu
"""
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User


class Command(BaseCommand):
    help = "Set user as staff and superuser so they can log in to Django admin; optionally set password."

    def add_arguments(self, parser):
        parser.add_argument("--username", type=str, required=True, help="Username (e.g. qrmenu)")
        parser.add_argument("--password", type=str, default=None, help="New password (optional)")

    def handle(self, *args, **options):
        username = options["username"].strip()
        password = options.get("password")

        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"User with username '{username}' not found."))
            return

        changed = []
        if not user.is_staff:
            user.is_staff = True
            changed.append("is_staff=True")
        if not user.is_superuser:
            user.is_superuser = True
            changed.append("is_superuser=True")
        if not user.is_active:
            user.is_active = True
            changed.append("is_active=True")

        if changed:
            user.save(update_fields=["is_staff", "is_superuser", "is_active"])
            self.stdout.write(self.style.SUCCESS(f"Updated: {', '.join(changed)}"))
        else:
            self.stdout.write("User already has staff and superuser flags.")

        if password:
            user.set_password(password)
            user.save(update_fields=["password"])
            self.stdout.write(self.style.SUCCESS("Password updated."))

        self.stdout.write(self.style.SUCCESS(f"Done. You can log in to /admin/ with username: {username}"))
