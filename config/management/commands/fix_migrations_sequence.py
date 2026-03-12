"""
Fix django_migrations.id sequence and optionally mark a migration as applied (fake).

Use when you see:
  - IntegrityError: duplicate key value violates unique constraint "django_migrations_pkey"
  - DuplicateTable when applying a migration (tables already exist)

Run on Scalingo:
  scalingo --app qrmenu run "python manage.py fix_migrations_sequence"
  scalingo --app qrmenu run "python manage.py fix_migrations_sequence --fake business_menu 0013_add_customer_order_payment"
  scalingo --app qrmenu run "python manage.py migrate"
"""
from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = "Fix django_migrations id sequence (PostgreSQL) and optionally fake a migration."

    def add_arguments(self, parser):
        parser.add_argument(
            "--fake",
            nargs=2,
            metavar=("APP", "NAME"),
            help="Insert migration record (app name, migration name) if not present. e.g. --fake business_menu 0013_add_customer_order_payment",
        )

    def handle(self, *args, **options):
        if connection.vendor != "postgresql":
            self.stdout.write("This command only runs on PostgreSQL. Skipping.")
            return
        with connection.cursor() as cursor:
            # 1) Fix sequence so next INSERT gets a new id
            cursor.execute("""
                SELECT setval(
                    pg_get_serial_sequence('django_migrations', 'id'),
                    (SELECT COALESCE(MAX(id), 1) FROM django_migrations)
                );
            """)
            self.stdout.write("Fixed django_migrations id sequence.")
            # 2) Optionally insert a fake migration record
            fake = options.get("fake")
            if fake:
                app_label, migration_name = fake
                cursor.execute(
                    "SELECT 1 FROM django_migrations WHERE app = %s AND name = %s",
                    [app_label, migration_name],
                )
                if cursor.fetchone():
                    self.stdout.write(f"Migration {app_label} {migration_name} already recorded.")
                else:
                    cursor.execute(
                        "INSERT INTO django_migrations (app, name, applied) VALUES (%s, %s, NOW())",
                        [app_label, migration_name],
                    )
                    self.stdout.write(f"Recorded migration {app_label} {migration_name} as applied (faked).")
        self.stdout.write(self.style.SUCCESS("Done. Run: python manage.py migrate"))
