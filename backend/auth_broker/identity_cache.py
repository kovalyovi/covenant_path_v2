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
overwrites the row, and every cached-lane login triggers a throttled background re-fetch
(enroll.refresh_cached_identity) — an email/stake change lands by the user's next login.

Best-effort by design: any failure (missing table, REST hiccup) returns None / no-ops, and the
login simply takes the full path it always took.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import requests

from lcr_client.logging_setup import get_logger

logger = get_logger()

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")


def _headers() -> dict:
    return {"apikey": SERVICE_KEY, "Authorization": f"Bearer {SERVICE_KEY}",
            "Content-Type": "application/json"}


def _key(username: str) -> str:
    return (username or "").strip().lower()


def get(username: str) -> dict | None:
    """Cached identity for a Church username, or None."""
    if not (SUPABASE_URL and SERVICE_KEY and _key(username)):
        return None
    try:
        r = requests.get(f"{SUPABASE_URL}/rest/v1/church_identities", headers=_headers(),
                         params={"username": f"eq.{_key(username)}", "limit": "1"}, timeout=6)
        rows = r.json() if r.status_code == 200 else []
        return rows[0] if rows else None
    except Exception as exc:  # noqa: BLE001 — cache miss must never break a login
        logger.info("identity cache read skipped: %s", exc)
        return None


def put(username: str, identity: dict, *, unit_number: int | None = None,
        stake_name: str | None = None, has_calling: bool | None = None) -> None:
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
        if identity.get("cmis_uuid"):  # never blank a stored uuid with a cached/partial identity
            row["cmis_uuid"] = identity.get("cmis_uuid")
        if unit_number is not None:
            row["unit_number"] = unit_number
        if stake_name is not None:
            row["stake_name"] = stake_name
        if has_calling is not None:
            row["has_calling"] = has_calling
        rows.append(row)
    try:
        requests.post(f"{SUPABASE_URL}/rest/v1/church_identities",
                      headers={**_headers(), "Prefer": "resolution=merge-duplicates,return=minimal"},
                      params={"on_conflict": "username"}, json=rows, timeout=8)
    except Exception as exc:  # noqa: BLE001
        logger.info("identity cache write skipped: %s", exc)


def set_unit(username: str, identity: dict, unit_number: int | None,
             stake_name: str | None, has_calling: bool | None = None) -> None:
    """Record the unit learned during the login eval (user_context) — this is what makes the NEXT
    login zero-LCR — plus the calling-gate outcome (migration 0044): the zero-LCR lane only
    authorizes when has_calling is TRUE, so a no-calling member can't ride the cache past the
    gate. Never raises."""
    if unit_number is None and has_calling is None:
        return
    put(username, identity, unit_number=unit_number, stake_name=stake_name,
        has_calling=has_calling)
