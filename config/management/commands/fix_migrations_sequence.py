"""
Fix PostgreSQL sequences so next INSERT gets a new id. Fixes:
  - django_migrations.id
  - django_content_type.id
  - auth_user.id (signup/create User fails with "auth_user_pkey" otherwise)

Use when you see:
  - IntegrityError: duplicate key value violates unique constraint "django_migrations_pkey"
  - IntegrityError: duplicate key value violates unique constraint "django_content_type_pkey"
  - IntegrityError: duplicate key value violates unique constraint "auth_user_pkey" (e.g. on signup)
  - IntegrityError: duplicate key value violates unique constraint "auth_permission_pkey" (after migrate)
  - IntegrityError: duplicate key value violates unique constraint "accounts_passwordresetcode_pkey" (forgot password)
  - DuplicateTable when applying a migration (tables already exist)

Run on Scalingo:
  scalingo --app qrmenu run "python manage.py fix_migrations_sequence"
  scalingo --app qrmenu run "python manage.py fix_migrations_sequence --fake business_menu 0013_add_customer_order_payment"
  scalingo --app qrmenu run "python manage.py migrate"
"""
from django.core.management.base import BaseCommand
from django.db import connection

# Tables whose id sequence we fix (table_name, sequence is on column "id")
SEQUENCE_TABLES = [
    "django_migrations",
    "django_content_type",
    "auth_user",
    "auth_permission",
    "business_menu_businessadmin",
    "business_menu_restaurant",
    "accounts_passwordresetcode",
]


class Command(BaseCommand):
    help = "Fix PostgreSQL sequences (django_migrations, django_content_type, auth_user, etc.) and optionally fake migrations."

    def add_arguments(self, parser):
        parser.add_argument(
            "--fake",
            nargs=2,
            action="append",
            metavar=("APP", "NAME"),
            help="Insert migration record (app name, migration name). Can be repeated. e.g. --fake business_menu 0013_add_customer_order_payment --fake business_menu 0014_order_service_and_restaurant_delivery",
        )

    def handle(self, *args, **options):
        if connection.vendor != "postgresql":
            self.stdout.write("This command only runs on PostgreSQL. Skipping.")
            return
        with connection.cursor() as cursor:
            # 1) Fix id sequence for known tables
            for table in SEQUENCE_TABLES:
                try:
                    # Table names are safe (no user input); quote for reserved words
                    quoted = f'"{table}"'
                    cursor.execute(
                        f"""
                        SELECT setval(
                            pg_get_serial_sequence({quoted}, 'id'),
                            (SELECT COALESCE(MAX(id), 1) FROM {quoted})
                        );
                        """
                    )
                    self.stdout.write(f"Fixed {table} id sequence.")
                except Exception as e:
                    self.stdout.write(self.style.WARNING(f"Could not fix {table} sequence: {e}"))
            # 2) Optionally insert fake migration record(s)
            fake_list = options.get("fake") or []
            for fake in fake_list:
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
