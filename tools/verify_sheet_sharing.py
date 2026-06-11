"""
READ-ONLY sheet-sharing audit (catalog row C7): for every stake sheet, diff WHO CAN currently
see it (Drive permissions, via the service account) against WHO SHOULD (the sharing policy in
backend/sheet_access.compute_recipients, fed by live user_roles + the missionary roster).

Never shares, never removes, never notifies — it only lists permissions and prints the diff, so
it's safe to run against production anytime ("verify it's shared to exactly the people it needs
to be, without pinging them").

Usage:
  python tools/verify_sheet_sharing.py                  # audit every stake with a spreadsheet_id
  python tools/verify_sheet_sharing.py --unit 999001    # one stake
  python tools/verify_sheet_sharing.py --file-id <id>   # ad-hoc: one file vs --expect a,b,c

Env: SUPABASE_DB_URL (the operator's connection string) + SHEETS_SERVICE_ACCOUNT (the SA json
path, same as sheets_sync). Exit code 1 when any sheet has missing/extra viewers.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.sheet_access import compute_recipients  # noqa: E402


def _drive():
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build

    from sheets_sync.service import CREATE_SCOPES, _service_account_file
    creds = Credentials.from_service_account_file(_service_account_file(), scopes=CREATE_SCOPES)
    return build("drive", "v3", credentials=creds), (
        getattr(creds, "service_account_email", "") or "").lower()


def _current_viewers(drive, file_id: str) -> dict[str, str]:
    """email -> role for every user permission on the file (read-only list, paged)."""
    out: dict[str, str] = {}
    page = None
    while True:
        resp = drive.permissions().list(
            fileId=file_id, fields="permissions(emailAddress,role,type),nextPageToken",
            pageToken=page).execute()
        for p in resp.get("permissions", []):
            em = (p.get("emailAddress") or "").lower()
            if p.get("type") == "user" and em:
                out[em] = p.get("role") or "?"
        page = resp.get("nextPageToken")
        if not page:
            break
    return out


def _diff(label: str, file_id: str, expected: set[str], drive, sa_email: str) -> bool:
    have = _current_viewers(drive, file_id)
    # The SA itself and the (human) owner hold the file by design — never "extra".
    sharable = {e for e, role in have.items() if role != "owner" and e != sa_email}
    missing = sorted(expected - sharable)
    extra = sorted(sharable - expected)
    ok = not missing and not extra
    print(f"\n{label}  (file {file_id})")
    print(f"  expected {len(expected)} · shared {len(sharable)} · "
          f"{'OK — exact match' if ok else 'MISMATCH'}")
    for e in missing:
        print(f"  MISSING  {e}  (entitled, but cannot see the sheet)")
    for e in extra:
        print(f"  EXTRA    {e}  (can see the sheet, but is not on the policy)")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description="read-only stake-sheet sharing audit")
    ap.add_argument("--unit", type=int, help="audit only this stake unit number")
    ap.add_argument("--file-id", help="ad-hoc: audit one Drive file id (skip the DB)")
    ap.add_argument("--expect", default="", help="with --file-id: comma-separated expected emails")
    args = ap.parse_args()

    drive, sa_email = _drive()

    if args.file_id:
        expected = {e.strip().lower() for e in args.expect.split(",") if "@" in e}
        return 0 if _diff("ad-hoc file", args.file_id, expected, drive, sa_email) else 1

    from backend import db
    conn = db.connect()
    try:
        with conn.cursor() as cur:
            cur.execute("select id, name, unit_number, spreadsheet_id, missionaries "
                        "from stakes where spreadsheet_id is not null"
                        + (" and unit_number=%s" if args.unit else ""),
                        (args.unit,) if args.unit else ())
            stakes = cur.fetchall()
        if not stakes:
            print("no stakes with a spreadsheet_id" + (f" (unit {args.unit})" if args.unit else ""))
            return 0
        all_ok = True
        for stake_id, name, unit, sheet_id, missionaries in stakes:
            with conn.cursor() as cur:
                cur.execute(
                    """select ur.email, ur.calling_name, ur.unit_id::text, u.name as unit_name
                       from user_roles ur left join units u on u.id = ur.unit_id
                       where ur.stake_id = %s""", (stake_id,))
                cols = [d[0] for d in cur.description]
                roles = [dict(zip(cols, r)) for r in cur.fetchall()]
            rec = compute_recipients(roles, missionaries or {})
            # The STAKE (master) sheet is what stakes.spreadsheet_id points at.
            ok = _diff(f"{name} ({unit}) — stake sheet", sheet_id, rec["stake"], drive, sa_email)
            all_ok = all_ok and ok
        return 0 if all_ok else 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
