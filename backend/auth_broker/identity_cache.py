"""
Broker-only identity cache (church_identities, migration 0042): Church username -> the identity we
verified on a prior FULL login (Okta + LCR SSO + /api/auth/me).

WHY: the LCR identity fetch is the slow, weather-dependent part of sign-in (measured 13s on a good
day, 90s+ while LCR is under load) — and for a repeat login it tells us nothing new. Okta has just
verified the password for `username`; this cache maps that verified principal to the email / name /
unit_number learned before, so the whole LCR leg is skipped. The login eval reuses unit_number for
its stored-credential check, making a routine repeat sign-in ZERO-LCR.

Trust model: consulted only AFTER a successful Okta password/MFA verification, and it only maps the
verified username to our own prior verified observation. Staleness heals: every full login
overwrites the row, and a `stale` hit (older than REFRESH_AFTER) triggers a background re-fetch.

Best-effort by design: any failure (missing table, REST hiccup) returns None / no-ops, and the
login simply takes the full path it always took.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import requests

from lcr_client.logging_setup import get_logger

logger = get_logger()

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
# A hit older than this still serves the login, but flags `stale` so the caller refreshes it
# in the background (catches the rare email/stake change without ever slowing a sign-in).
REFRESH_AFTER = timedelta(days=7)


def _headers() -> dict:
    return {"apikey": SERVICE_KEY, "Authorization": f"Bearer {SERVICE_KEY}",
            "Content-Type": "application/json"}


def _key(username: str) -> str:
    return (username or "").strip().lower()


def get(username: str) -> dict | None:
    """Cached identity for a Church username, or None. Adds `stale: bool`."""
    if not (SUPABASE_URL and SERVICE_KEY and _key(username)):
        return None
    try:
        r = requests.get(f"{SUPABASE_URL}/rest/v1/church_identities", headers=_headers(),
                         params={"username": f"eq.{_key(username)}", "limit": "1"}, timeout=6)
        rows = r.json() if r.status_code == 200 else []
        if not rows:
            return None
        row = rows[0]
        stale = True
        try:
            updated = datetime.fromisoformat(str(row.get("updated_at")).replace("Z", "+00:00"))
            stale = datetime.now(timezone.utc) - updated > REFRESH_AFTER
        except Exception:  # noqa: BLE001 — unparseable timestamp just means "treat as stale"
            pass
        row["stale"] = stale
        return row
    except Exception as exc:  # noqa: BLE001 — cache miss must never break a login
        logger.info("identity cache read skipped: %s", exc)
        return None


def put(username: str, identity: dict, *, unit_number: int | None = None,
        stake_name: str | None = None) -> None:
    """Upsert the verified identity under the TYPED username and under the canonical LCR username
    when different (members sign in with either form). Omitted columns keep their stored values
    (PostgREST updates only payload columns), so a put without unit_number preserves a known unit.
    Never raises."""
    email = (identity.get("email") or "").lower()
    if not (SUPABASE_URL and SERVICE_KEY and email):
        return
    keys = {_key(username), _key(identity.get("username") or "")} - {""}
    if not keys:
        return
    rows = []
    for k in sorted(keys):
        row = {"username": k, "email": email, "name": identity.get("name"),
               "cmis_id": identity.get("cmis_id"),
               "updated_at": datetime.now(timezone.utc).isoformat()}
        if unit_number is not None:
            row["unit_number"] = unit_number
        if stake_name is not None:
            row["stake_name"] = stake_name
        rows.append(row)
    try:
        requests.post(f"{SUPABASE_URL}/rest/v1/church_identities",
                      headers={**_headers(), "Prefer": "resolution=merge-duplicates,return=minimal"},
                      params={"on_conflict": "username"}, json=rows, timeout=8)
    except Exception as exc:  # noqa: BLE001
        logger.info("identity cache write skipped: %s", exc)


def set_unit(username: str, identity: dict, unit_number: int | None,
             stake_name: str | None) -> None:
    """Record the unit learned during the login eval (user_context) — this is what makes the NEXT
    login zero-LCR. Never raises."""
    if unit_number is None:
        return
    put(username, identity, unit_number=unit_number, stake_name=stake_name)
