"""
Fix PostgreSQL sequences so next INSERT gets a new id.
Used by signup (and fix_migrations_sequence command) when DB was imported and sequences are out of sync.
"""
from django.db import connection

SIGNUP_SEQUENCE_TABLES = (
    "auth_user",
    "business_menu_businessadmin",
    "business_menu_restaurant",
    "accounts_passwordresetcode",
)


def fix_sequence_for_table(table_name: str) -> bool:
    """Set sequence for table.id to MAX(id). Returns True if done, False if not PostgreSQL or error."""
    if connection.vendor != "postgresql":
        return False
    if table_name not in SIGNUP_SEQUENCE_TABLES:
        return False
    try:
        with connection.cursor() as cursor:
            # pg_get_serial_sequence wants table name as text; FROM needs quoted identifier
            quoted_table = connection.ops.quote_name(table_name)
            cursor.execute(
                "SELECT setval(pg_get_serial_sequence(%s, 'id'), (SELECT COALESCE(MAX(id), 0) FROM " + quoted_table + "))",
                [table_name],
            )
    except Exception:
        return False
    return True


def fix_auth_and_signup_sequences() -> None:
    """Fix sequences for auth_user and business_menu tables used during signup. Call before User.objects.create()."""
    for table in SIGNUP_SEQUENCE_TABLES:
        fix_sequence_for_table(table)
