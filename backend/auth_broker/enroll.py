"""
Delegated stake onboarding (#51): persist a leader's captured LCR session as their stake's
credential so the daily sync can keep that stake current.

Reuses the proven client parsing — LcrClient.user_context() for the stake, and
covenant_path_access() for what the session can pull (coverage) — encrypts the session with
envelope encryption (credentials._encrypt_envelope), and stores it via the SECURITY DEFINER
enroll_stake_credential RPC (so the service-role broker writes the RLS-locked tables without
broad grants). The caller guards every call — a failure here must never break login.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import requests

from lcr_client.logging_setup import get_logger

logger = get_logger()
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")


def _client_from_cookies(cookies: list[dict]):
    """Build an LcrClient from captured cookies (no auto-login, no shared state file)."""
    from lcr_client import LcrClient
    from lcr_client.auth import LcrSession
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    p = Path(path)
    p.write_text(json.dumps({"cookies": cookies}), encoding="utf-8")
    try:
        session = LcrSession(storage_state_path=p, auto_login=False)  # loads cookies into memory
    finally:
        p.unlink(missing_ok=True)  # cookies are in-memory now; don't leave the file around
    return LcrClient(session=session)


def persist(cookies: list[dict], identity: dict) -> dict:
    """Resolve the enroller's stake + coverage and store the encrypted credential. Returns a
    status dict ({stake, unit_number, complete, missing}). Raises on hard failure (caller guards)."""
    if not (SUPABASE_URL and SERVICE_KEY):
        raise RuntimeError("supabase not configured (SUPABASE_URL / SERVICE_ROLE_KEY)")
    from lcr_client.access import covenant_path_access
    from backend import credentials, onboarding

    client = _client_from_cookies(cookies)
    ctx = client.user_context()
    access = covenant_path_access(client)  # best-effort name enrichment is internally guarded
    coverage = onboarding.coverage_of(access)
    rank = onboarding.access_rank(access)
    role_ids = sorted({p["id"] for p in access.get("runner_positions", [])
                       if isinstance(p.get("id"), int)})
    blob = credentials._encrypt_envelope(
        json.dumps({"cookies": cookies, "refresh_token": identity.get("refresh_token")}).encode("utf-8"))

    r = requests.post(
        f"{SUPABASE_URL}/rest/v1/rpc/enroll_stake_credential",
        headers={"apikey": SERVICE_KEY, "Authorization": f"Bearer {SERVICE_KEY}",
                 "Content-Type": "application/json"},
        json={
            "p_unit_number": ctx.unit_number,
            "p_stake_name": ctx.unit_name,
            "p_principal_name": identity.get("name") or identity.get("email"),
            "p_principal_email": (identity.get("email") or "").lower(),
            "p_granting_role_ids": role_ids,
            "p_credential_enc": blob,
            "p_coverage": coverage,
            "p_access_rank": rank,
            "p_expires_at": None,
        },
        timeout=60)
    if r.status_code >= 300:
        raise RuntimeError(f"enroll RPC failed ({r.status_code}): {r.text[:160]}")
    logger.info("enrolled stake %s (%s): coverage_complete=%s rank=%s",
                ctx.unit_name, ctx.unit_number, coverage["complete"], rank)
    initial_sync = _kickoff_initial_sync(ctx.unit_number)
    return {"stake": ctx.unit_name, "unit_number": ctx.unit_number,
            "complete": coverage["complete"], "missing": coverage["missing"],
            "initial_sync": initial_sync}


def _kickoff_initial_sync(unit_number: int) -> bool:
    """For a brand-new stake (no data scraped yet), mark it 'running' and dispatch the
    daily-sync workflow so the leader doesn't wait for the next scheduled run. The app then
    shows the "setting up your stake" syncing state until the run lands. Best-effort: if
    GitHub isn't configured or the stake already has data, this is a no-op."""
    from datetime import datetime, timezone
    try:
        from backend.auth_broker import admin
        if not admin.github_configured():
            return False
        sb = {"apikey": SERVICE_KEY, "Authorization": f"Bearer {SERVICE_KEY}"}
        r = requests.get(f"{SUPABASE_URL}/rest/v1/stakes", headers=sb,
                         params={"select": "id", "unit_number": f"eq.{unit_number}", "limit": "1"},
                         timeout=30)
        rows = r.json() if r.status_code == 200 else []
        if not rows:
            return False
        stake_id = rows[0]["id"]
        if (admin._count_where("members", {"stake_id": f"eq.{stake_id}"}) or 0) > 0:
            return False  # already has data — the daily run keeps it fresh
        requests.patch(f"{SUPABASE_URL}/rest/v1/stakes",
                       headers={**sb, "Content-Type": "application/json", "Prefer": "return=minimal"},
                       params={"id": f"eq.{stake_id}"},
                       json={"sync_state": "running",
                             "sync_started_at": datetime.now(timezone.utc).isoformat()},
                       timeout=30)
        admin.dispatch("daily-sync.yml", inputs={"targets": "supabase"})
        logger.info("kicked off initial sync for new stake unit=%s", unit_number)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("initial-sync kickoff skipped (non-fatal): %s", exc)
        return False
