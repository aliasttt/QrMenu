"""
Django management command: copy PostgreSQL data from source DB (MIGRATE_SOURCE_URL) to current app DB.
Usage on Scalingo one-off:
  scalingo --app qrmenu run python manage.py migrate_from_source_db
Requires: MIGRATE_SOURCE_URL set to the source postgres URL (e.g. from mywebsite).
"""
import os

from django.core.management.base import BaseCommand

try:
    import psycopg2
    from psycopg2 import sql
    from psycopg2.sql import SQL, Identifier
    from psycopg2.extras import execute_values
except ImportError:
    psycopg2 = None


def get_tables(conn):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT tablename FROM pg_tables
            WHERE schemaname = 'public' AND tablename NOT LIKE 'pg_%%'
            ORDER BY tablename
        """)
        return [r[0] for r in cur.fetchall()]


def get_columns(conn, table):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s
            ORDER BY ordinal_position
        """, (table,))
        return [r[0] for r in cur.fetchall()]


def reset_sequences(conn):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT table_name, column_name
            FROM information_schema.columns
            WHERE table_schema = 'public' AND column_default LIKE 'nextval%%'
            ORDER BY table_name
        """)
        for table, column in cur.fetchall():
            try:
                cur.execute(
                    SQL("SELECT setval(pg_get_serial_sequence({}, {}), COALESCE((SELECT max({}) FROM {}), 1))").format(
                        Identifier(table), Identifier(column), Identifier(column), Identifier(table)
                    )
                )
            except Exception:
                pass


def copy_table_data(old_conn, new_conn, table, batch=500):
    cols = get_columns(old_conn, table)
    if not cols:
        return 0
    col_list = ", ".join(f'"{c}"' for c in cols)
    insert_sql = f'INSERT INTO "{table}" ({col_list}) VALUES %s'
    with old_conn.cursor() as rcur:
        rcur.execute(f'SELECT {col_list} FROM "{table}"')
        count = 0
        with new_conn.cursor() as wcur:
            while True:
                rows = rcur.fetchmany(batch)
                if not rows:
                    break
                execute_values(wcur, insert_sql, rows, page_size=batch)
                count += len(rows)
    return count


class Command(BaseCommand):
    help = "Copy PostgreSQL data from MIGRATE_SOURCE_URL to current DATABASE_URL (data-only)."

    def handle(self, *args, **options):
        if not psycopg2:
            self.stderr.write(self.style.ERROR("psycopg2 is required: pip install psycopg2-binary"))
            return
        source_url = os.environ.get("MIGRATE_SOURCE_URL") or os.getenv("MIGRATE_SOURCE_URL")
        target_url = os.environ.get("SCALINGO_POSTGRESQL_URL") or os.environ.get("DATABASE_URL")
        if not source_url:
            self.stderr.write(self.style.ERROR("Set MIGRATE_SOURCE_URL to the source Postgres URL (e.g. from mywebsite)."))
            return
        if not target_url:
            self.stderr.write(self.style.ERROR("DATABASE_URL / SCALINGO_POSTGRESQL_URL not set."))
            return
        self.stdout.write("Connecting to source...")
        old_conn = psycopg2.connect(source_url)
        self.stdout.write("Connecting to target...")
        new_conn = psycopg2.connect(target_url)
        old_conn.autocommit = True
        new_conn.autocommit = False
        try:
            tables = get_tables(old_conn)
            to_copy = []
            for table in tables:
                target_cols = get_columns(new_conn, table)
                if not target_cols:
                    self.stdout.write(f"  Skip {table} (not in target)")
                    continue
                src_cols = get_columns(old_conn, table)
                common = [c for c in src_cols if c in target_cols]
                if not common:
                    self.stdout.write(f"  Skip {table} (no common columns)")
                    continue
                to_copy.append(table)
            # Order so FKs are satisfied: django_content_type first, then auth_*, django_*, accounts_*, business_menu (restaurant before category/menuitem/etc)
            order_prefix = (
                "django_content_type", "auth_permission", "auth_user", "auth_group",
                "auth_group_permissions", "auth_user_groups", "auth_user_user_permissions",
                "django_migrations", "django_admin_log", "django_session",
                "accounts_business", "accounts_emailverificationcode", "accounts_passwordresetcode",
                "accounts_profile", "accounts_useractivity",
                "business_menu_businessadmin", "business_menu_restaurant", "business_menu_menutheme",
                "business_menu_restaurantsettings", "business_menu_category", "business_menu_menuset",
                "business_menu_cloudinaryimage", "business_menu_menuitem", "business_menu_menuitemimage",
                "business_menu_menuqrcode", "business_menu_package", "business_menu_packageitem",
            )
            ordered = [t for t in order_prefix if t in to_copy]
            ordered += [t for t in to_copy if t not in ordered]
            to_copy = ordered
            self.stdout.write(f"Tables to copy: {to_copy}")
            # Note: session_replication_role requires superuser on Scalingo; skip and rely on TRUNCATE CASCADE + insert order
            if to_copy:
                with new_conn.cursor() as cur:
                    cur.execute(
                        sql.SQL("TRUNCATE TABLE {} RESTART IDENTITY CASCADE").format(
                            sql.SQL(", ").join(sql.Identifier(t) for t in to_copy)
                        )
                    )
                new_conn.commit()
            for table in to_copy:
                try:
                    n = copy_table_data(old_conn, new_conn, table)
                    new_conn.commit()
                    self.stdout.write(self.style.SUCCESS(f"  {table}: {n} rows"))
                except Exception as e:
                    new_conn.rollback()
                    self.stdout.write(self.style.WARNING(f"  {table}: SKIP ({e})"))
            reset_sequences(new_conn)
            new_conn.commit()
            self.stdout.write(self.style.SUCCESS("Done."))
        finally:
            old_conn.close()
            new_conn.close()
