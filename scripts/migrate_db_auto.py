#!/usr/bin/env python3
"""
Migrate PostgreSQL data from Scalingo app 'mywebsite' to 'qrmenu'.
Gets DATABASE URLs from Scalingo CLI (or from env DATABASE_URL_OLD / DATABASE_URL_NEW), then copies data (data-only; tables must exist).
When running from your PC, use db-tunnel and pass local URLs via env (see run_with_tunnels.ps1).
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse, urlunparse

# Prefer psycopg2 (Django default); fallback to psycopg
try:
    import psycopg2
    from psycopg2 import sql
    from psycopg2.sql import SQL, Identifier
    from psycopg2.extras import execute_values
    HAS_PSYCOPG = True
    PSYCOPG2 = True
except ImportError:
    try:
        import psycopg
        from psycopg import sql
        from psycopg.sql import SQL, Identifier
        HAS_PSYCOPG = True
        PSYCOPG2 = False
    except ImportError:
        HAS_PSYCOPG = False

if not HAS_PSYCOPG:
    print("Install psycopg2 or psycopg: pip install psycopg2-binary", file=sys.stderr)
    sys.exit(1)


def get_scalingo_env(app: str, var: str = "SCALINGO_POSTGRESQL_URL") -> str:
    out = subprocess.run(
        ["scalingo", "--app", app, "env-get", var],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if out.returncode != 0:
        raise SystemExit(f"Scalingo CLI failed for app {app!r}: {out.stderr or out.stdout}")
    url = (out.stdout or "").strip()
    if not url:
        raise SystemExit(f"Empty {var} for app {app!r}. Is PostgreSQL addon linked?")
    return url


def get_tables(conn) -> list[str]:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT tablename FROM pg_tables
            WHERE schemaname = 'public'
            AND tablename NOT LIKE 'pg_%'
            ORDER BY tablename
        """)
        return [r[0] for r in cur.fetchall()]


def get_columns(conn, table: str) -> list[str]:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s
            ORDER BY ordinal_position
        """, (table,))
        return [r[0] for r in cur.fetchall()]


def reset_sequences(conn) -> None:
    """Reset serial sequences to max(id) for all public tables."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT table_name, column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND column_default LIKE 'nextval%%'
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


def copy_table_data(old_conn, new_conn, table: str, batch: int = 500) -> int:
    cols = get_columns(old_conn, table)
    if not cols:
        return 0
    col_list = ", ".join(f'"{c}"' for c in cols)
    insert_sql = f'INSERT INTO "{table}" ({col_list}) VALUES %s'
    with old_conn.cursor(name="read_" + table) if PSYCOPG2 else old_conn.cursor() as rcur:
        if PSYCOPG2:
            rcur.itersize = batch
        rcur.execute(f'SELECT {col_list} FROM "{table}"')
        count = 0
        with new_conn.cursor() as wcur:
            while True:
                rows = rcur.fetchmany(batch)
                if not rows:
                    break
                if PSYCOPG2:
                    execute_values(wcur, insert_sql, rows, page_size=batch)
                else:
                    placeholders = ", ".join("%s" for _ in cols)
                    for row in rows:
                        wcur.execute(f'INSERT INTO "{table}" ({col_list}) VALUES ({placeholders})', row)
                count += len(rows)
    return count


def url_to_local(url: str, port: int) -> str:
    """Replace host and port in postgres URL with 127.0.0.1 and given port."""
    parsed = urlparse(url)
    netloc = f"127.0.0.1:{port}"
    return urlunparse(parsed._replace(netloc=netloc))


def main() -> None:
    # Running on Scalingo one-off: source URL in MIGRATE_SOURCE_URL, target in DATABASE_URL/SCALINGO_POSTGRESQL_URL
    migrate_source = os.environ.get("MIGRATE_SOURCE_URL") or os.getenv("MIGRATE_SOURCE_URL")
    scalingo_pg = os.environ.get("SCALINGO_POSTGRESQL_URL") or os.environ.get("DATABASE_URL") or os.getenv("SCALINGO_POSTGRESQL_URL") or os.getenv("DATABASE_URL")
    if migrate_source and scalingo_pg:
        print("Using MIGRATE_SOURCE_URL (source) and DATABASE_URL (target) from environment (Scalingo one-off).")
        old_url = migrate_source
        new_url = scalingo_pg
    else:
        old_url = os.environ.get("DATABASE_URL_OLD") or os.getenv("DATABASE_URL_OLD")
        new_url = os.environ.get("DATABASE_URL_NEW") or os.getenv("DATABASE_URL_NEW")
        tunnel_old = os.environ.get("TUNNEL_OLD_PORT") or os.getenv("TUNNEL_OLD_PORT")
        tunnel_new = os.environ.get("TUNNEL_NEW_PORT") or os.getenv("TUNNEL_NEW_PORT")
        if tunnel_old and tunnel_new and (not old_url or not new_url):
            print("Using db-tunnel ports; fetching URLs from Scalingo...")
            old_url = get_scalingo_env("mywebsite")
            new_url = get_scalingo_env("qrmenu")
            old_url = url_to_local(old_url, int(tunnel_old))
            new_url = url_to_local(new_url, int(tunnel_new))
            print("Connecting via 127.0.0.1 (tunnel).")
        elif not old_url or not new_url:
            print("Fetching database URLs from Scalingo...")
            old_url = old_url or get_scalingo_env("mywebsite")
            new_url = new_url or get_scalingo_env("qrmenu")
    print("Connecting to source (mywebsite)...")
    old_conn = psycopg2.connect(old_url) if PSYCOPG2 else psycopg.connect(old_url)
    print("Connecting to target (qrmenu)...")
    new_conn = psycopg2.connect(new_url) if PSYCOPG2 else psycopg.connect(new_url)
    old_conn.autocommit = True
    new_conn.autocommit = False
    try:
        tables = get_tables(old_conn)
        to_copy = []
        for table in tables:
            target_cols = get_columns(new_conn, table)
            if not target_cols:
                print(f"  Skip {table} (not in target)")
                continue
            src_cols = get_columns(old_conn, table)
            common = [c for c in src_cols if c in target_cols]
            if not common:
                print(f"  Skip {table} (no common columns)")
                continue
            to_copy.append(table)
        print(f"Tables to copy: {to_copy}")
        # Disable triggers and FK checks on target
        with new_conn.cursor() as cur:
            cur.execute("SET session_replication_role = 'replica';")
        new_conn.commit()
        # Truncate all target tables at once (CASCADE handles dependencies)
        if to_copy:
            with new_conn.cursor() as cur:
                cur.execute(
                    sql.SQL("TRUNCATE TABLE {} RESTART IDENTITY CASCADE").format(
                        sql.SQL(", ").join(sql.Identifier(t) for t in to_copy)
                    )
                )
            new_conn.commit()
        for table in to_copy:
            n = copy_table_data(old_conn, new_conn, table)
            new_conn.commit()
            print(f"  {table}: {n} rows")
        # Re-enable triggers
        with new_conn.cursor() as cur:
            cur.execute("SET session_replication_role = 'origin';")
        new_conn.commit()
        # Reset serial sequences
        reset_sequences(new_conn)
        new_conn.commit()
        print("Done.")
    finally:
        old_conn.close()
        new_conn.close()


if __name__ == "__main__":
    main()
