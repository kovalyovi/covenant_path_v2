"""
Sync the v2 covenant-path report to the master Google Sheet.

Mirrors the existing sheet's behavior (so data stays the same) while cutting API
calls vs the v1 updater:
  - one batchGet for headers + existing data,
  - merge by member name, PRESERVING manual columns P+ ("1st temple visit", "Notes")
    AND preserving an existing cell when our scrape couldn't fetch a gated field
    (so a partial/low-access run never erases good data),
  - one update for the main sheet, one batchUpdate for all per-unit tabs,
  - one append for the changelog, one update for the timestamp,
  - formatting copy is OPT-IN (rarely changes; it was the bulk of v1's requests).

Auth: a Google service account (Sheets API). Path from env SHEETS_SERVICE_ACCOUNT,
else sheets_sync/service_account.json, else the v1 file for dev convenience. The
service-account email must have Editor access to the target spreadsheet.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

from sheets_sync.row_mapper import DATA_WIDTH, GATED_COLUMNS, to_row

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
# drive.file lets the service account CREATE per-stake spreadsheets and SHARE the ones it created
# (narrower than full Drive — it can only touch files it made). Requires the Drive API enabled on
# the GCP project (one-time toggle). Used only by create_and_share_spreadsheet.
CREATE_SCOPES = SCOPES + ["https://www.googleapis.com/auth/drive.file"]
DEFAULT_SHEET = "New member progress"
CHANGELOG = "Changelog"
_SA_CANDIDATES = [
    os.environ.get("SHEETS_SERVICE_ACCOUNT"),
    str(Path(__file__).resolve().parent / "service_account.json"),
    "D:/dev/member_covenant_path/service_account.json",  # dev fallback
]


def _service_account_file() -> str:
    for p in _SA_CANDIDATES:
        if p and Path(p).exists():
            return p
    raise FileNotFoundError(
        "No service account file. Set SHEETS_SERVICE_ACCOUNT or drop "
        "sheets_sync/service_account.json (Editor-shared on the target sheet)."
    )


def create_and_share_spreadsheet(title: str, viewer_emails: list[str],
                                 service_account_file: str | None = None) -> str:
    """Create a NEW spreadsheet for one stake and share it READ-ONLY with the given emails (the
    stake's leadership + onboarder). Returns the new spreadsheet id. Best-effort sharing — a bad
    email is skipped. Requires the Drive API enabled on the GCP project (else raises; the caller
    degrades gracefully)."""
    creds = Credentials.from_service_account_file(
        service_account_file or _service_account_file(), scopes=CREATE_SCOPES)
    sheets = build("sheets", "v4", credentials=creds)
    drive = build("drive", "v3", credentials=creds)
    ss = sheets.spreadsheets().create(
        body={"properties": {"title": title},
              "sheets": [{"properties": {"title": DEFAULT_SHEET}}]}).execute()
    sid = ss["spreadsheetId"]
    for em in {e.strip().lower() for e in viewer_emails if e and "@" in e}:
        try:
            drive.permissions().create(
                fileId=sid, sendNotificationEmail=False,
                body={"type": "user", "role": "reader", "emailAddress": em}).execute()
        except Exception:  # noqa: BLE001 — one bad address shouldn't block the rest
            pass
    return sid


def share_spreadsheet(spreadsheet_id: str, viewer_emails: list[str],
                      service_account_file: str | None = None) -> None:
    """Add read-only viewers to an existing (app-created) spreadsheet. Idempotent per email."""
    creds = Credentials.from_service_account_file(
        service_account_file or _service_account_file(), scopes=CREATE_SCOPES)
    drive = build("drive", "v3", credentials=creds)
    for em in {e.strip().lower() for e in viewer_emails if e and "@" in e}:
        try:
            drive.permissions().create(
                fileId=spreadsheet_id, sendNotificationEmail=False,
                body={"type": "user", "role": "reader", "emailAddress": em}).execute()
        except Exception:  # noqa: BLE001
            pass


class SheetsSync:
    def __init__(self, spreadsheet_id: str, sheet_name: str = DEFAULT_SHEET,
                 service_account_file: str | None = None) -> None:
        self.spreadsheet_id = spreadsheet_id
        self.sheet = sheet_name
        creds = Credentials.from_service_account_file(
            service_account_file or _service_account_file(), scopes=SCOPES)
        self._svc = build("sheets", "v4", credentials=creds).spreadsheets()

    # --- public ---------------------------------------------------------------

    def diagnose(self) -> dict:
        meta = self._svc.get(spreadsheetId=self.spreadsheet_id,
                             fields="properties.title,sheets.properties.title").execute()
        return {"title": meta["properties"]["title"],
                "tabs": [s["properties"]["title"] for s in meta["sheets"]]}

    def sync(self, members: list[dict], write: bool = True, units: bool = True,
             copy_formats: bool = False, preserve_units: set[str] | None = None) -> dict:
        """Merge `members` into the sheet. Returns a summary (also computed on dry-run).

        preserve_units: full unit names that FAILED to scrape this run — their existing
        rows are kept as-is (not deleted), so a flaky/erroring unit never wipes its
        members from the full-replace sheet.
        """
        from sheets_sync.row_mapper import format_unit
        preserve = {format_unit(u) for u in (preserve_units or set())}
        members = sorted(members, key=lambda m: (m.get("unit") or "", m.get("name") or ""))
        headers, existing = self._fetch_existing()
        existing_by_name = {str(r[0]): r for r in existing if r and r[0]}

        merged, changes = self._merge(members, existing_by_name, headers, preserve)
        summary = {
            "title": None, "members": len(members),
            "added": sum(c["field"] == "Added" for c in changes),
            "removed": sum(c["field"] == "Removed" for c in changes),
            "modified": sum(c["field"] not in ("Added", "Removed") for c in changes),
            "wrote": False,
        }
        if not write:
            summary["sample_row"] = merged[0] if merged else None
            return summary

        self._write_main(merged)
        self._timestamp()
        if changes and existing:
            self._append_changelog(changes)
        if units:
            self._write_units(members, headers)
        if copy_formats:
            self._copy_formats()
        summary["wrote"] = True
        return summary

    # --- internals ------------------------------------------------------------

    def _fetch_existing(self) -> tuple[list, list]:
        """One batchGet: header row (row 2) + data (A3:Z1000)."""
        res = self._svc.values().batchGet(
            spreadsheetId=self.spreadsheet_id,
            ranges=[f"{self.sheet}!2:2", f"{self.sheet}!A3:Z1000"]).execute()
        vr = res.get("valueRanges", [])
        headers = (vr[0].get("values", [[]]) or [[]])[0] if vr else []
        existing = vr[1].get("values", []) if len(vr) > 1 else []
        return headers, existing

    def _merge(self, members, existing_by_name, headers, preserve_units=None):
        """Build merged rows; preserve P+ manual cols, gated cells on empty, and the
        rows of units that failed to scrape (preserve_units, stripped names)."""
        preserve_units = preserve_units or set()
        merged, changes = [], []
        for m in members:
            row = to_row(m)
            old = existing_by_name.get(str(m.get("name") or ""))
            if old:
                # preserve an existing value where our scrape came back empty (gated/blocked)
                for c in GATED_COLUMNS:
                    if (not row[c]) and c < len(old) and old[c]:
                        row[c] = old[c]
                # change detection (skip the two duration columns 3 & 5 — derived)
                for i, new_val in enumerate(row):
                    old_val = old[i] if i < len(old) else ""
                    if new_val != old_val and i not in (3, 5):
                        changes.append({"name": m.get("name"), "ward": row[1],
                                        "field": headers[i] if i < len(headers) else f"Col{i+1}",
                                        "old": old_val, "new": new_val})
                if len(old) > DATA_WIDTH:        # keep manual columns P+
                    row += old[DATA_WIDTH:]
            else:
                changes.append({"name": m.get("name"), "ward": row[1],
                                "field": "Added", "old": "", "new": "new"})
            merged.append(row)
        new_names = {str(m.get("name") or "") for m in members}
        for name in existing_by_name.keys() - new_names:
            old = existing_by_name[name]
            unit_b = old[1] if len(old) > 1 else ""
            if unit_b in preserve_units:
                merged.append(old)              # keep rows of units we couldn't scrape
            else:
                changes.append({"name": name, "ward": unit_b,
                                "field": "Removed", "old": "existing", "new": ""})
        # keep the sheet ordered by unit then name
        merged.sort(key=lambda r: (r[1] if len(r) > 1 else "", r[0] if r else ""))
        return merged, changes

    def _write_main(self, merged: list[list]) -> None:
        self._svc.values().clear(spreadsheetId=self.spreadsheet_id,
                                 range=f"{self.sheet}!A3:Z1000", body={}).execute()
        if merged:
            self._svc.values().update(
                spreadsheetId=self.spreadsheet_id, range=f"{self.sheet}!A3",
                valueInputOption="RAW", body={"values": merged}).execute()

    def _timestamp(self) -> None:
        stamp = datetime.now().strftime("%B %d, %Y %I:%M:%S %p")
        self._svc.values().update(
            spreadsheetId=self.spreadsheet_id, range=f"{self.sheet}!A1",
            valueInputOption="RAW", body={"values": [[f"Last updated: {stamp}"]]}).execute()

    def _append_changelog(self, changes: list[dict]) -> None:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        rows = [[ts, c["name"], c["ward"], c["field"], c["old"], c["new"]] for c in changes]
        head = self._svc.values().get(spreadsheetId=self.spreadsheet_id,
                                      range=f"{CHANGELOG}!A1:F1").execute()
        if not head.get("values"):
            rows.insert(0, ["Updated Date", "Name", "Ward", "Field", "Old Value", "New Value"])
            self._svc.values().update(spreadsheetId=self.spreadsheet_id, range=f"{CHANGELOG}!A1",
                                      valueInputOption="RAW", body={"values": rows}).execute()
        else:
            self._svc.values().append(spreadsheetId=self.spreadsheet_id, range=f"{CHANGELOG}!A:F",
                                      valueInputOption="RAW", body={"values": rows}).execute()

    def _write_units(self, members: list[dict], headers: list) -> None:
        by_unit: dict[str, list] = {}
        for m in members:
            unit = m.get("unit")
            if unit:
                by_unit.setdefault(unit, []).append(to_row(m))
        if not by_unit:
            return
        existing_tabs = set(self.diagnose()["tabs"])
        add_reqs = [{"addSheet": {"properties": {"title": u}}}
                    for u in by_unit if u not in existing_tabs]
        if add_reqs:
            self._svc.batchUpdate(spreadsheetId=self.spreadsheet_id,
                                  body={"requests": add_reqs}).execute()
        # clear all unit data ranges, then one batchUpdate of header+rows per tab
        for u in by_unit:
            self._svc.values().clear(spreadsheetId=self.spreadsheet_id,
                                     range=f"{u}!A3:Z1000", body={}).execute()
        data = [{"range": f"{u}!A1", "values": [headers] + rows} if headers
                else {"range": f"{u}!A3", "values": rows}
                for u, rows in by_unit.items()]
        self._svc.values().batchUpdate(
            spreadsheetId=self.spreadsheet_id,
            body={"valueInputOption": "RAW", "data": data}).execute()

    def _copy_formats(self) -> None:
        """Opt-in: copy main-sheet formatting to unit tabs (the costly part of v1)."""
        meta = self._svc.get(spreadsheetId=self.spreadsheet_id,
                             fields="sheets(properties(sheetId,title))").execute()
        ids = {s["properties"]["title"]: s["properties"]["sheetId"] for s in meta["sheets"]}
        main = ids.get(self.sheet)
        if main is None:
            return
        src = {"sheetId": main, "startRowIndex": 0, "endRowIndex": 1000,
               "startColumnIndex": 0, "endColumnIndex": 26}
        reqs = []
        for title, sid in ids.items():
            if title in (self.sheet, CHANGELOG):
                continue
            dst = {**src, "sheetId": sid}
            for pt in ("PASTE_FORMAT", "PASTE_CONDITIONAL_FORMATTING", "PASTE_DATA_VALIDATION"):
                reqs.append({"copyPaste": {"source": src, "destination": dst, "pasteType": pt}})
        if reqs:
            self._svc.batchUpdate(spreadsheetId=self.spreadsheet_id,
                                  body={"requests": reqs}).execute()
