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
      * no entry yet and his markdown is non-empty  -> INSERT (created_at = HIS updated_at, so the
                                                       note keeps its ORIGINAL date, not today's)
      * entry exists and his markdown CHANGED       -> UPDATE body (updated_at = this run)
      * entry exists and matches                    -> skip (idempotent)
  - Markdown is stored RAW (bold/italics markers preserved) — the web renders it (D59).
  - Uuids of his that we don't know (his manual people / null-personUuid people he keyed on the LCR
    `id` / other-mission members) are skipped and counted, never guessed.

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


def _norm_uuid(s: str | None) -> str:
    """Normalize a person id for matching: dashes stripped, lowercased. Ricky's app keys some notes
    by a hyphenated personUuid and others by a bare 32-hex id (personUuid null → LCR `id`), and our
    members carry both shapes — so match on the normalized form, but always WRITE our member's real
    person_uuid (what the web/RLS query by)."""
    return (s or "").replace("-", "").strip().lower()


def our_members(conn, stake_unit: str | None) -> list[dict]:
    """Every member we could attach a note to: person_uuid -> (stake_id, unit_id)."""
    q = ("select m.person_uuid, m.stake_id, m.unit_id from members m"
         + (" join stakes s on s.id = m.stake_id where s.unit_number = %s" if stake_unit else ""))
    with conn.cursor() as cur:
        cur.execute(q, (stake_unit,) if stake_unit else None)
        return [{"uuid": r[0], "stake_id": r[1], "unit_id": r[2]} for r in cur.fetchall() if r[0]]


def fetch_gas_notes(url: str, token: str, uuids: list[str]) -> dict[str, dict]:
    """Sweep his GAS backend per uuid -> {uuid: {body, at}} for every note he has (`at` = his
    updated_at, preserved as the imported note's original date)."""
    notes: dict[str, dict] = {}
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
            notes[uuid] = {"body": body["markdown"], "at": (body.get("updated_at") or "").strip() or None}
        if i % 25 == 0:
            print(f"  …swept {i}/{len(uuids)} ({len(notes)} notes so far)")
        time.sleep(0.15)  # be gentle: Apps Script quota is ~20k req/day but latency-throttled
    return notes


def read_csv_notes(path: str) -> dict[str, dict]:
    """His sheet's notes tab exported as CSV: uuid, markdown, updated_at, client_id.
    Returns {uuid: {body, at}} — `at` = his updated_at (kept as the note's original date)."""
    notes: dict[str, dict] = {}
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            uuid = (row.get("uuid") or "").strip()
            markdown = row.get("markdown") or ""
            if uuid and markdown.strip():  # store RAW (markers/whitespace intact), skip empties
                notes[uuid] = {"body": markdown, "at": (row.get("updated_at") or "").strip() or None}
    return notes


def import_notes(conn, notes: dict[str, dict], members: list[dict],
                 author_email: str, author_name: str, dry_run: bool) -> dict:
    # Match on the NORMALIZED id (dash/case-insensitive) but write our member's REAL person_uuid.
    by_norm = {_norm_uuid(m["uuid"]): m for m in members}
    stats = {"inserted": 0, "updated": 0, "unchanged": 0, "unmatched": 0}
    unmatched: list[str] = []
    with conn.cursor() as cur:
        for uuid, note in notes.items():
            markdown, at = note["body"], note.get("at")
            m = by_norm.get(_norm_uuid(uuid))
            if not m:
                stats["unmatched"] += 1
                unmatched.append(uuid[:8])
                continue
            our_uuid = m["uuid"]  # our canonical person_uuid (what the web + RLS key on)
            cur.execute("select id, body from member_comments"
                        " where member_person_uuid = %s and lower(author_email) = lower(%s)",
                        (our_uuid, author_email))
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
                    # created_at = HIS updated_at (preserve the original date) when present + parseable;
                    # otherwise fall back to the column default (now()).
                    cur.execute(
                        "insert into member_comments (stake_id, unit_id, member_person_uuid,"
                        " author_email, author_name, body, created_at)"
                        " values (%s, %s, %s, %s, %s, %s, coalesce(%s::timestamptz, now()))",
                        (m["stake_id"], m["unit_id"], our_uuid, author_email, author_name, markdown, at))
    if not dry_run:
        conn.commit()
    if unmatched:
        print(f"  unmatched uuids (not in our DB — his null-personUuid/manual/other-mission people): "
              f"{', '.join(unmatched)}…")
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
