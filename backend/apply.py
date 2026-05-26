"""
Apply the SQL migrations to the Supabase Postgres database.

  python -m backend.apply        # applies backend/migrations/*.sql in order

Idempotent (uses IF NOT EXISTS / drop-and-create policies). Needs SUPABASE_DB_URL.
"""

import sys

from backend import db


def main() -> int:
    conn = db.connect()
    try:
        applied = db.apply_migrations(conn)
        # quick sanity: list created tables
        with conn.cursor() as cur:
            cur.execute("select table_name from information_schema.tables "
                        "where table_schema='public' order by table_name")
            tables = [r[0] for r in cur.fetchall()]
    finally:
        conn.close()
    print(f"[+] applied: {', '.join(applied)}")
    print(f"[+] public tables: {', '.join(tables)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
