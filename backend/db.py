"""
Postgres/Supabase access for the covenant-path platform.

Connects via SUPABASE_DB_URL (the postgres role → bypasses RLS, so the scraper can
write freely while app readers stay RLS-scoped). Provides migration application and
idempotent upserts for stakes / units / members.

Env:
  SUPABASE_DB_URL = postgresql://postgres:<password>@db.<ref>.supabase.co:5432/postgres
"""

from __future__ import annotations

import os
from pathlib import Path

import psycopg2
import psycopg2.extras

from lcr_client.logging_setup import get_logger

logger = get_logger()
MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

# the 13 covenant-path fields + extras we persist (member dict key -> column)
_MEMBER_COLUMNS = [
    "person_uuid", "name", "unit_name", "baptism_date", "birth_date", "friends",
    "aaronic_priesthood", "melchizedek_priesthood", "calling",
    "ministering_brothers_sisters", "ministering_assignment", "temple_recommend",
    "patriarchal_blessing", "living_ordinance", "membership_duration", "sex",
    "kind", "baptism_goal_date",  # new_member|investigator|returning + planned baptism date
    "details",  # jsonb — the rich progress subtree (dict; wrapped as Json on write)
]


def db_url() -> str:
    url = os.environ.get("SUPABASE_DB_URL")
    if not url or "[YOUR-PASSWORD]" in url:
        raise RuntimeError(
            "SUPABASE_DB_URL not set (or still a placeholder). Put the full connection "
            "string from Supabase → Settings → Database into .env."
        )
    return url


def connect():
    from dotenv import load_dotenv
    load_dotenv()
    return psycopg2.connect(db_url())


def apply_migrations(conn, migrations_dir: Path = MIGRATIONS_DIR) -> list[str]:
    applied = []
    with conn.cursor() as cur:
        for sql_file in sorted(migrations_dir.glob("*.sql")):
            logger.info("applying migration %s", sql_file.name)
            cur.execute(sql_file.read_text(encoding="utf-8"))
            applied.append(sql_file.name)
    conn.commit()
    return applied


def upsert_stake(conn, unit_number: int, name: str) -> str:
    with conn.cursor() as cur:
        cur.execute(
            """insert into stakes (unit_number, name) values (%s, %s)
               on conflict (unit_number) do update set name = excluded.name
               returning id""", (unit_number, name))
        return cur.fetchone()[0]


def upsert_unit(conn, stake_id: str, unit_number: int, name: str, unit_type: str | None) -> str:
    with conn.cursor() as cur:
        cur.execute(
            """insert into units (stake_id, unit_number, name, unit_type)
               values (%s, %s, %s, %s)
               on conflict (unit_number) do update
                 set name = excluded.name, unit_type = excluded.unit_type, stake_id = excluded.stake_id
               returning id""", (stake_id, unit_number, name, unit_type))
        return cur.fetchone()[0]


def upsert_members(conn, stake_id: str, members: list[dict],
                   unit_id_by_number: dict[int, str],
                   unit_id_by_name: dict[str, str] | None = None) -> int:
    """Idempotent upsert keyed by (stake_id, person_uuid). Returns rows written.

    unit_id resolves by unit_number first, then unit name (so reports generated before
    `unit_number` existed still map to a unit). `unit_name` column ← the report's `unit`.
    """
    unit_id_by_name = unit_id_by_name or {}
    rows = []
    for m in members:
        if not m.get("person_uuid"):
            continue
        unit_name = m.get("unit") or m.get("unit_name")
        unit_id = unit_id_by_number.get(m.get("unit_number")) or unit_id_by_name.get(unit_name)
        vals = []
        for c in _MEMBER_COLUMNS:
            if c == "unit_name":
                vals.append(unit_name)
            elif c == "details":
                v = m.get("details")
                vals.append(psycopg2.extras.Json(v) if v is not None else None)
            else:
                vals.append(m.get(c))
        rows.append((stake_id, unit_id, *vals))
    if not rows:
        return 0
    cols = "stake_id, unit_id, " + ", ".join(_MEMBER_COLUMNS)
    # on conflict, refresh everything except the conflict key (person_uuid); unit_id
    # isn't in _MEMBER_COLUMNS so add it once.
    update_cols = ["unit_id"] + [c for c in _MEMBER_COLUMNS if c != "person_uuid"]
    updates = ", ".join(f"{c} = excluded.{c}" for c in update_cols)
    sql = (f"insert into members ({cols}) values %s "
           f"on conflict (stake_id, person_uuid) do update set {updates}")
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(cur, sql, rows)
    conn.commit()
    return len(rows)


def touch_stake_synced(conn, stake_id: str) -> None:
    with conn.cursor() as cur:
        cur.execute("update stakes set last_synced_at = now() where id = %s", (stake_id,))
    conn.commit()


def update_stake_kpis(conn, stake_id: str, kpis: dict) -> None:
    with conn.cursor() as cur:
        cur.execute("update stakes set kpis = %s, kpis_updated_at = now() where id = %s",
                    (psycopg2.extras.Json(kpis), stake_id))
    conn.commit()


def insert_diagnostics(conn, stake_id: str | None, kind: str, payload: dict) -> None:
    with conn.cursor() as cur:
        cur.execute("insert into sync_diagnostics (stake_id, kind, payload) values (%s,%s,%s)",
                    (stake_id, kind, psycopg2.extras.Json(payload)))
    conn.commit()
