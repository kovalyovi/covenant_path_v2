"""
Create + share a stake's spreadsheet in the connected leader's Drive (M7).

The leader OWNS the sheet (the platform service account can't create files — 0 storage). We create
it with the leader's OAuth access token, then share it **with the service account (Editor)** so the
daily sync's existing `SheetsSync` writes the data exactly as before, and **read-only with the
stake's leadership**. So: OAuth provides the create capability + ownership; the service account does
the per-run data write on a sheet that lives in the leader's Drive.
"""

from __future__ import annotations

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from lcr_client.logging_setup import get_logger
from sheets_sync.service import DEFAULT_SHEET

logger = get_logger()


def _svc(access_token: str, api: str, ver: str):
    return build(api, ver, credentials=Credentials(token=access_token), cache_discovery=False)


def _share(drive, file_id: str, email: str | None, role: str) -> None:
    if not email:
        return
    try:
        drive.permissions().create(
            fileId=file_id, sendNotificationEmail=False,
            body={"type": "user", "role": role, "emailAddress": email}).execute()
    except Exception as exc:  # noqa: BLE001 — a share failure must not abort the sync
        logger.warning("drive share %s (%s) skipped: %s", email, role, str(exc)[:120])


def ensure_sheet(access_token: str, title: str, service_account_email: str,
                 share_emails: list[str], file_id: str | None = None) -> str:
    """Return the stake's spreadsheet id in the leader's Drive — creating it on first use. Always
    (re)shares with the service account (writer) + leadership (reader); both are idempotent."""
    drive = _svc(access_token, "drive", "v3")
    if not file_id:
        sheets = _svc(access_token, "sheets", "v4")
        # Create with the "New member progress" tab (not the default "Sheet1") so SheetsSync can
        # write to it — exactly like the service-account create path.
        created = sheets.spreadsheets().create(
            body={"properties": {"title": title},
                  "sheets": [{"properties": {"title": DEFAULT_SHEET}}]},
            fields="spreadsheetId").execute()
        file_id = created["spreadsheetId"]
        logger.info("created OAuth-Drive spreadsheet %s in the leader's Drive", file_id)
    _share(drive, file_id, service_account_email, "writer")  # so the SA-based sync can write data
    for em in share_emails:
        _share(drive, file_id, em, "reader")
    return file_id
