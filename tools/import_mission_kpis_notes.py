"""
Import per-person notes from Ricky Bloomfield's Mission-KPIs backend into member_comments.

His store (rickybloomfield/Mission-KPIs, docs/notes-backend.gs): ONE markdown document per
person, keyed by the LCR person UUID — the SAME uuids as our `members.person_uuid` — behind a
Google Apps Script web app (`.../exec`) that answers `GET ?uuid=<uuid>&token=<secret>` per
person (there is NO list-all endpoint, so we sweep OUR member uuids and collect his 200s).
Apps Script web deployments always answer HTTP 200 and mirror the real status in the body
(`{"status": 404, ...}`), so we branch on the body.

What to request from Ricky (either works, the first is zero-effort for him):
  a) the Web-app URL (ends in /exec) + the SHARED_SECRET value  → --gas-url/--token
  b) a CSV export of the "notes" tab (uuid, markdown, updated_at, client_id) → --csv

Import model (dedup-safe, re-runnable):
  - Each member gets AT MOST ONE imported thread entry, keyed by (member_person_uuid,
    author_email = --author-email). His note is one evolving markdown doc, so:
      * no entry yet and his markdown is non-empty  -> INSERT (created_at = this run)
      * entry exists and his markdown CHANGED       -> UPDATE body (updated_at = this run)
      * entry exists and matches                    -> skip (idempotent)
  - Markdown is stored RAW (bold/italics markers preserved) — the web renders it (D59).
  - Uuids of his that we don't know (his manual people / other-mission members) are skipped
    and counted, never guessed.

Writes via SUPABASE_DB_URL (service lane, same as the sync). PII posture: prints counts and
uuid PREFIXES only, never names or note text.

Usage:
  python tools/import_mission_kpis_notes.py --gas-url https://script.google.com/.../exec \
      --token <secret> [--stake 503991] [--dry-run]
  python tools/import_mission_kpis_notes.py --csv notes_export.csv [--dry-run]
  (RICKY_NOTES_URL / RICKY_NOTES_TOKEN in .env work as defaults for --gas-url/--token.)
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests
from dotenv import load_dotenv

AUTHOR_EMAIL_DEFAULT = "mission-kpis-import@membercovenantpath.org"
AUTHOR_NAME_DEFAULT = "Ricky Bloomfield (imported)"


def our_members(conn, stake_unit: str | None) -> list[dict]:
    """Every member we could attach a note to: person_uuid -> (stake_id, unit_id)."""
    q = ("select m.person_uuid, m.stake_id, m.unit_id from members m"
         + (" join stakes s on s.id = m.stake_id where s.unit_number = %s" if stake_unit else ""))
    with conn.cursor() as cur:
        cur.execute(q, (stake_unit,) if stake_unit else None)
        return [{"uuid": r[0], "stake_id": r[1], "unit_id": r[2]} for r in cur.fetchall() if r[0]]


def fetch_gas_notes(url: str, token: str, uuids: list[str]) -> dict[str, str]:
    """Sweep his GAS backend per uuid -> {uuid: markdown} for every note he has."""
    notes: dict[str, str] = {}
    sess = requests.Session()
    for i, uuid in enumerate(uuids, 1):
        try:
            r = sess.get(url, params={"uuid": uuid, "token": token}, timeout=30)
            body = json.loads(r.text)
        except Exception as exc:  # noqa: BLE001 — one bad fetch shouldn't sink the sweep
            print(f"  fetch failed for {uuid[:8]}…: {exc}")
            continue
        status = body.get("status", r.status_code)
        if status == 401:
            raise SystemExit("GAS backend says unauthorized — is the token right?")
        if status == 200 and (body.get("markdown") or "").strip():
            notes[uuid] = body["markdown"]
        if i % 25 == 0:
            print(f"  …swept {i}/{len(uuids)} ({len(notes)} notes so far)")
        time.sleep(0.15)  # be gentle: Apps Script quota is ~20k req/day but latency-throttled
    return notes


def read_csv_notes(path: str) -> dict[str, str]:
    """His sheet's notes tab exported as CSV: uuid, markdown, updated_at, client_id."""
    notes: dict[str, str] = {}
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            uuid = (row.get("uuid") or "").strip()
            markdown = row.get("markdown") or ""
            if uuid and markdown.strip():  # store RAW (markers/whitespace intact), skip empties
                notes[uuid] = markdown
    return notes


def import_notes(conn, notes: dict[str, str], members: list[dict],
                 author_email: str, author_name: str, dry_run: bool) -> dict:
    by_uuid = {m["uuid"]: m for m in members}
    stats = {"inserted": 0, "updated": 0, "unchanged": 0, "unmatched": 0}
    unmatched: list[str] = []
    with conn.cursor() as cur:
        for uuid, markdown in notes.items():
            m = by_uuid.get(uuid)
            if not m:
                stats["unmatched"] += 1
                unmatched.append(uuid[:8])
                continue
            cur.execute("select id, body from member_comments"
                        " where member_person_uuid = %s and lower(author_email) = lower(%s)",
                        (uuid, author_email))
            row = cur.fetchone()
            if row and row[1] == markdown:
                stats["unchanged"] += 1
            elif row:
                stats["updated"] += 1
                if not dry_run:
                    cur.execute("update member_comments set body = %s, updated_at = now(),"
                                " updated_by = %s where id = %s", (markdown, author_email, row[0]))
            else:
                stats["inserted"] += 1
                if not dry_run:
                    cur.execute(
                        "insert into member_comments (stake_id, unit_id, member_person_uuid,"
                        " author_email, author_name, body) values (%s, %s, %s, %s, %s, %s)",
                        (m["stake_id"], m["unit_id"], uuid, author_email, author_name, markdown))
    if not dry_run:
        conn.commit()
    if unmatched:
        print(f"  unmatched uuids (his manual people / not in our DB): {', '.join(unmatched)}…")
    return stats


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--gas-url", default=os.getenv("RICKY_NOTES_URL"),
                    help="his Apps Script /exec URL (or RICKY_NOTES_URL in .env)")
    ap.add_argument("--token", default=os.getenv("RICKY_NOTES_TOKEN"),
                    help="his SHARED_SECRET (or RICKY_NOTES_TOKEN in .env)")
    ap.add_argument("--csv", help="alternatively: a CSV export of his notes tab")
    ap.add_argument("--stake", help="limit the sweep/import to one stake unit number")
    ap.add_argument("--author-email", default=AUTHOR_EMAIL_DEFAULT,
                    help="dedup key + stored author_email of imported entries")
    ap.add_argument("--author-name", default=AUTHOR_NAME_DEFAULT)
    ap.add_argument("--dry-run", action="store_true", help="report what would change, write nothing")
    args = ap.parse_args()

    load_dotenv()
    if not args.csv and not (args.gas_url and args.token):
        ap.error("need --csv, or --gas-url + --token (RICKY_NOTES_URL/RICKY_NOTES_TOKEN)")

    import psycopg2

    conn = psycopg2.connect(os.environ["SUPABASE_DB_URL"])
    try:
        members = our_members(conn, args.stake)
        print(f"{len(members)} member(s) in scope" + (f" (stake {args.stake})" if args.stake else ""))
        if args.csv:
            notes = read_csv_notes(args.csv)
            print(f"CSV: {len(notes)} non-empty note(s)")
        else:
            print("sweeping his notes backend (one GET per member uuid)…")
            notes = fetch_gas_notes(args.gas_url, args.token, [m["uuid"] for m in members])
            print(f"backend: {len(notes)} note(s) found")
        stats = import_notes(conn, notes, members, args.author_email, args.author_name,
                             args.dry_run)
        print(("DRY RUN — nothing written. " if args.dry_run else "") + f"result: {stats}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
