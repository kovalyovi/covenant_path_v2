"""
Seed a stake's missionary transfer schedule from Ricky Bloomfield's Mission-KPIs export.

His "transfer_dates" tab is a flat list of mission transfer-cycle dates (~every 6 weeks):
  transfer_id, transfer_date       e.g.  t-2026-07-23, 2026-07-23

This tool upserts those rows into OUR `transfer_dates` table for one stake (default: Raleigh,
503991). Idempotent / re-runnable: keyed on (stake_id, transfer_id), so re-import updates a moved
date and never duplicates. After this, our DB is the source of truth — the web banner + ward goals
read it, and Ricky's app can pull it back over the broker.

Writes via SUPABASE_DB_URL (service lane, same as the sync). Prints counts only.

Usage:
  python tools/import_transfer_dates.py --csv transfer_dates.csv [--stake 503991] [--dry-run]
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

from backend import db

DEFAULT_STAKE = "503991"  # Raleigh North Carolina Stake


def read_csv(path: str) -> list[tuple[str, str]]:
    """(transfer_id, transfer_date) pairs. Tolerant of a stray leading column / duplicate header
    (his export header is `transfer_id\ttransfer_date,transfer_date`) — we key strictly off the two
    named columns and ISO `YYYY-MM-DD` dates, skipping anything malformed."""
    out: list[tuple[str, str]] = []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            tid = (row.get("transfer_id") or "").strip()
            date = (row.get("transfer_date") or "").strip()
            if len(date) == 10 and date[4] == "-" and date[7] == "-":
                if not tid:
                    tid = f"t-{date}"
                out.append((tid, date))
    return out


def resolve_stake_id(conn, stake_unit: str) -> str | None:
    with conn.cursor() as cur:
        cur.execute("select id from stakes where unit_number = %s", (stake_unit,))
        r = cur.fetchone()
        return r[0] if r else None


def upsert(conn, stake_id: str, rows: list[tuple[str, str]], dry_run: bool) -> dict:
    stats = {"inserted": 0, "updated": 0, "unchanged": 0}
    with conn.cursor() as cur:
        for tid, date in rows:
            cur.execute("select transfer_date::text from transfer_dates "
                        "where stake_id = %s and transfer_id = %s", (stake_id, tid))
            existing = cur.fetchone()
            if existing is None:
                stats["inserted"] += 1
            elif existing[0] != date:
                stats["updated"] += 1
            else:
                stats["unchanged"] += 1
                continue
            if not dry_run:
                cur.execute(
                    """insert into transfer_dates (stake_id, transfer_id, transfer_date, updated_by)
                       values (%s, %s, %s, 'mission-kpis-import')
                       on conflict (stake_id, transfer_id)
                       do update set transfer_date = excluded.transfer_date,
                                     updated_by = excluded.updated_by, updated_at = now()""",
                    (stake_id, tid, date))
    if not dry_run:
        conn.commit()
    return stats


def main() -> int:
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True, help="his transfer_dates export (transfer_id, transfer_date)")
    ap.add_argument("--stake", default=DEFAULT_STAKE, help="stake unit_number (default Raleigh 503991)")
    ap.add_argument("--dry-run", action="store_true", help="report what WOULD change, write nothing")
    args = ap.parse_args()

    rows = read_csv(args.csv)
    if not rows:
        print("no valid transfer dates in the CSV — nothing to do")
        return 1
    print(f"read {len(rows)} transfer date(s) from {args.csv}")

    conn = db.connect()
    try:
        stake_id = resolve_stake_id(conn, args.stake)
        if not stake_id:
            print(f"no stake with unit_number {args.stake} — is it enrolled/synced?")
            return 1
        stats = upsert(conn, stake_id, rows, args.dry_run)
    finally:
        conn.close()
    verb = "would " if args.dry_run else ""
    print(f"[+] {verb}inserted {stats['inserted']}, {verb}updated {stats['updated']}, "
          f"unchanged {stats['unchanged']} (stake {args.stake})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
