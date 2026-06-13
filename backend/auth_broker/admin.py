"""
Admin/ops console support for the broker.

Three jobs, all over HTTP so the broker needs no DB connection or extra deps beyond
`requests` (which it already has):

  1. verify_admin(bearer)  — confirm a Supabase access token belongs to an app_admin
     (GoTrue /auth/v1/user -> email -> app_admins lookup via the service-role REST API).
  2. summary()             — system health + data freshness + row counts from Supabase.
  3. GitHub Actions        — list recent runs, dispatch (rescrape + repopulate Sheets),
     re-run, poll status, and read the commit changelog. Degrades gracefully (returns
     "not configured") when GITHUB_TOKEN is unset, so the console still loads.

Config (env): SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY (already set for session minting),
GITHUB_TOKEN (fine-grained PAT: Actions read+write, Contents read), GITHUB_REPO.
"""

from __future__ import annotations

import os
import re

import requests

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "kovalyovi/covenant_path_v2")
_TIMEOUT = 15

# Only these workflows may be dispatched/re-run from the console — never arbitrary input.
DISPATCHABLE = {
    "daily-sync.yml": "Rescrape LCR + repopulate Sheets & Supabase",
    "keep-broker-warm.yml": "Ping the broker to keep it warm",
}


class AdminError(Exception):
    """Misconfiguration or upstream failure (-> 503)."""


class NotAdmin(Exception):
    """Caller is not an authenticated admin (-> 403)."""


class NotFound(Exception):
    """Requested resource doesn't exist (-> 404)."""


# --- auth -------------------------------------------------------------------

def _sb_headers() -> dict:
    if not (SUPABASE_URL and SERVICE_KEY):
        raise AdminError("supabase not configured (SUPABASE_URL / SERVICE_ROLE_KEY)")
    return {"apikey": SERVICE_KEY, "Authorization": f"Bearer {SERVICE_KEY}"}


def verify_user(authorization: str) -> str:
    """`authorization` = "Bearer <supabase access token>". Returns the signed-in user's
    verified email (GoTrue-checked), or raises NotAdmin / AdminError. No admin requirement."""
    token = (authorization or "").removeprefix("Bearer ").strip()
    if not token:
        raise NotAdmin("no bearer token")
    if not (SUPABASE_URL and SERVICE_KEY):
        raise AdminError("supabase not configured")
    try:
        u = requests.get(
            f"{SUPABASE_URL}/auth/v1/user",
            headers={"apikey": SERVICE_KEY, "Authorization": f"Bearer {token}"},
            timeout=_TIMEOUT,
        )
    except requests.RequestException as e:
        raise AdminError(f"supabase auth unreachable: {e}") from e
    if u.status_code != 200:
        raise NotAdmin("invalid or expired session")
    email = (u.json().get("email") or "").strip().lower()
    if not email:
        raise NotAdmin("token has no email")
    return email


def verify_admin(authorization: str) -> str:
    """Like verify_user, but also requires app_admins membership (checked with the service key)."""
    email = verify_user(authorization)
    a = requests.get(
        f"{SUPABASE_URL}/rest/v1/app_admins",
        headers=_sb_headers(), params={"select": "email", "email": f"eq.{email}"},
        timeout=_TIMEOUT,
    )
    if a.status_code == 200 and a.json():
        return email
    raise NotAdmin("not an admin")


# --- health / freshness -----------------------------------------------------

def _count(table: str) -> int | None:
    # No `select` column — count=exact is independent of the projection, and not every
    # table has an `id` (e.g. app_admins is keyed by email).
    try:
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/{table}",
            headers={**_sb_headers(), "Prefer": "count=exact", "Range": "0-0"},
            timeout=_TIMEOUT,
        )
    except requests.RequestException:
        return None
    cr = r.headers.get("Content-Range", "")  # e.g. "0-0/112"
    if "/" in cr:
        total = cr.rsplit("/", 1)[-1]
        return None if total in ("*", "") else int(total)
    return None

def _one(table: str, params: dict) -> dict | None:
    try:
        r = requests.get(f"{SUPABASE_URL}/rest/v1/{table}", headers=_sb_headers(),
                         params=params, timeout=_TIMEOUT)
    except requests.RequestException:
        return None
    rows = r.json() if r.status_code == 200 else []
    return rows[0] if rows else None


def _count_where(table: str, params: dict) -> int | None:
    """count=exact with a filter (e.g. members for one stake_id). Like _count but scoped."""
    try:
        r = requests.get(f"{SUPABASE_URL}/rest/v1/{table}",
                         headers={**_sb_headers(), "Prefer": "count=exact", "Range": "0-0"},
                         params=params, timeout=_TIMEOUT)
    except requests.RequestException:
        return None
    cr = r.headers.get("Content-Range", "")  # e.g. "0-0/112"
    if "/" in cr:
        total = cr.rsplit("/", 1)[-1]
        return None if total in ("*", "") else int(total)
    return None


def recent_diagnostics(limit: int = 60) -> list[dict]:
    """Recent sync/probe diagnostics rows (latest first). Enough history (default 60) for the
    endpoint-troubleshoot console to chart latency/error trends and scope per-stake (#13–15)."""
    try:
        r = requests.get(f"{SUPABASE_URL}/rest/v1/sync_diagnostics", headers=_sb_headers(),
                         params={"select": "run_at,kind,stake_id,payload",
                                 "order": "run_at.desc", "limit": limit}, timeout=_TIMEOUT)
    except requests.RequestException:
        return []
    return r.json() if r.status_code == 200 else []


# --- tiny TTL cache for the heavy read endpoints (feedback #4: ops console took 15s) -------------
# The console fires 6+ parallel reads (Supabase REST + GitHub API) on every open; a short cache makes
# reloads instant and halves Render free-tier CPU. Mutations bust it so revoke/wipe/sync reflect
# immediately. Per-process (the broker is a single instance).
import time as _time

_CACHE: dict[str, tuple[float, object]] = {}


def _cached(key: str, ttl: float, fn):
    hit = _CACHE.get(key)
    now = _time.monotonic()
    if hit and now - hit[0] < ttl:
        return hit[1]
    val = fn()
    _CACHE[key] = (now, val)
    return val


def _cache_clear() -> None:
    _CACHE.clear()


def _jobs_last_7d() -> dict:
    """stake_id -> number of sync runs in the last 7 days (from sync_diagnostics), for the ops
    cross-stake view (#9). One query, tallied client-side (no per-stake round trips)."""
    from datetime import datetime, timedelta, timezone
    since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    try:
        r = requests.get(f"{SUPABASE_URL}/rest/v1/sync_diagnostics", headers=_sb_headers(),
                         params={"select": "stake_id", "kind": "eq.sync",
                                 "run_at": f"gte.{since}", "limit": "10000"}, timeout=_TIMEOUT)
    except requests.RequestException:
        return {}
    out: dict[str, int] = {}
    for row in (r.json() if r.status_code == 200 else []):
        sid = row.get("stake_id")
        if sid:
            out[sid] = out.get(sid, 0) + 1
    return out


def endpoint_health(days: int = 14) -> dict:
    """Cross-run per-endpoint health TREND from the telemetry every sync/probe already records
    (sync_diagnostics.payload.requests). Answers the passive half of "what request rate is safe?":
    aggregates calls / errors / latency per endpoint over the window and buckets the error rate by
    HOUR OF DAY (is LCR healthier at night? → schedule the heavy sync there). Zero added load on LCR
    — it's pure read-back of what we've already observed during normal operation."""
    from datetime import datetime, timedelta, timezone
    since = (datetime.now(timezone.utc) - timedelta(days=max(1, days))).isoformat()
    try:
        r = requests.get(f"{SUPABASE_URL}/rest/v1/sync_diagnostics", headers=_sb_headers(),
                         params={"select": "run_at,kind,payload",
                                 "kind": "in.(sync,probe)", "run_at": f"gte.{since}",
                                 "order": "run_at.desc", "limit": "2000"}, timeout=_TIMEOUT)
    except requests.RequestException:
        return {"days": days, "runs": 0, "endpoints": [], "by_hour": {}}
    rows = r.json() if r.status_code == 200 else []

    agg: dict[str, dict] = {}
    hour_calls: dict[int, int] = {}
    hour_err: dict[int, int] = {}
    runs = 0
    for row in rows:
        reqs = ((row.get("payload") or {}).get("requests") or {})
        eps = reqs.get("endpoints") or []
        if not eps:
            continue
        runs += 1
        hour = _hour_of(row.get("run_at"))
        for ep in eps:
            name = _norm_endpoint(str(ep.get("endpoint") or ""))
            a = agg.setdefault(name, {"calls": 0, "errors": 0, "ms_sum": 0, "max_ms": 0, "runs": 0})
            calls, errors = int(ep.get("calls") or 0), int(ep.get("errors") or 0)
            a["calls"] += calls
            a["errors"] += errors
            a["ms_sum"] += int(ep.get("avg_ms") or 0) * calls  # weight avg by call volume
            a["max_ms"] = max(a["max_ms"], int(ep.get("max_ms") or 0))
            a["runs"] += 1
            if hour is not None:
                hour_calls[hour] = hour_calls.get(hour, 0) + calls
                hour_err[hour] = hour_err.get(hour, 0) + errors

    endpoints = []
    for name, a in sorted(agg.items(), key=lambda kv: kv[1]["errors"], reverse=True):
        err_pct = round(100 * a["errors"] / a["calls"], 1) if a["calls"] else 0.0
        endpoints.append({
            "endpoint": name, "calls": a["calls"], "errors": a["errors"], "error_pct": err_pct,
            "avg_ms": round(a["ms_sum"] / a["calls"]) if a["calls"] else 0, "max_ms": a["max_ms"],
            "runs_seen": a["runs"],
            # verdict at the sync's CURRENT pace — the passive read on whether we're already too hot.
            "verdict": ("healthy" if err_pct < 2 else "watch" if err_pct < 10 else "hot"),
        })
    by_hour = {str(h): {"calls": hour_calls[h], "errors": hour_err.get(h, 0),
                        "error_pct": round(100 * hour_err.get(h, 0) / hour_calls[h], 1)}
               for h in sorted(hour_calls) if hour_calls[h]}
    return {"days": days, "runs": runs, "endpoints": endpoints, "by_hour": by_hour}


def _hour_of(run_at: str | None) -> int | None:
    if not run_at:
        return None
    try:
        from datetime import datetime
        return datetime.fromisoformat(run_at.replace("Z", "+00:00")).hour
    except (ValueError, TypeError):
        return None


# Same route-pattern collapse the ops client uses (#13-15): defend against OLD rows captured before
# the metrics normalizer, so per-endpoint trends group cleanly across the whole window.
_ID_SEG = re.compile(r"^([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[0-9a-f]{16,}|\d+)$", re.I)


def _norm_endpoint(ep: str) -> str:
    try:
        from urllib.parse import urlparse
        path = urlparse(ep).path or ep
    except (ValueError, TypeError):
        path = ep

    def _seg(s: str) -> str:
        # Collapse: an opaque id, an already-{id} segment, OR a HALF-normalized id left by the pre-fix
        # metrics normalizer — its old substring sub mangled ids that start with digits into
        # "{id}<hextail>" (e.g. ".../one-work/details/{id}c392993ba544f4abedeb596b7f6fc73"). Those
        # rows otherwise survive forever as distinct "hot" endpoints in the trend; merging them on read
        # (matches apps/web AdminPage.normEndpoint) fixes the "View all" list without a data migration.
        return "{id}" if (s.startswith("{id}") or _ID_SEG.match(s)) else s

    return "/".join(_seg(seg) if seg else seg for seg in path.split("/"))


def _reauths_30d() -> dict:
    """stake_unit -> number of credential (re)authorizations in the last 30 days (login_audit
    outcome='enrolled'). Cadence visibility: how often each stake actually needs a fresh re-auth."""
    from datetime import datetime, timedelta, timezone
    since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    try:
        r = requests.get(f"{SUPABASE_URL}/rest/v1/login_audit", headers=_sb_headers(),
                         params={"select": "stake_unit", "outcome": "eq.enrolled",
                                 "at": f"gte.{since}", "limit": "5000"}, timeout=_TIMEOUT)
    except requests.RequestException:
        return {}
    out: dict[int, int] = {}
    for row in (r.json() if r.status_code == 200 else []):
        su = row.get("stake_unit")
        if su is not None:
            out[su] = out.get(su, 0) + 1
    return out


def _member_counts() -> dict:
    """stake_id -> member count in ONE query. Replaces the per-stake count loop in enrolled_stakes()
    that made it N+1 round-trips (a slow/hung count there dropped the whole ops request → the admin's
    'Enrolled stakes: Failed to fetch')."""
    try:
        r = requests.get(f"{SUPABASE_URL}/rest/v1/members", headers=_sb_headers(),
                         params={"select": "stake_id", "limit": "100000"}, timeout=_TIMEOUT)
    except requests.RequestException:
        return {}
    out: dict[str, int] = {}
    for row in (r.json() if r.status_code == 200 else []):
        sid = row.get("stake_id")
        if sid:
            out[sid] = out.get(sid, 0) + 1
    return out


def _jwt_sub(token: str) -> str:
    """Extract the 'sub' (auth_id UUID) from a Supabase JWT without re-verifying.
    Caller must have already verified the token via verify_user() before calling this."""
    import base64, json as _json  # noqa: E401
    try:
        parts = token.split(".")
        pad = parts[1] + "=" * (-len(parts[1]) % 4)
        return _json.loads(base64.urlsafe_b64decode(pad)).get("sub", "")
    except Exception:
        return ""


def enrollment_status(email: str, auth_id: str) -> dict:
    """Return stake enrollment status for a signed-in user (email + auth_id from JWT).
    Queries user_roles -> stakes -> stake_credentials via service-role REST."""
    headers = _sb_headers()
    # 1. Find user's role → stake_id. Match by bound auth_id OR verified email, mirroring RLS
    #    (migration 0004) and reports._scope: an email/Google login's auth_id is the Supabase uid —
    #    never the LCR person uuid (calling-derived rows) nor the trigger-bound email — so the old
    #    auth_id-only lookup missed every email-login leader (e.g. a stake president), wrongly showing
    #    "sync not enabled / no members" for a fully-synced stake (#9).
    def _roles_by(params: dict) -> list:
        r = requests.get(f"{SUPABASE_URL}/rest/v1/user_roles", headers=headers,
                         params={"select": "stake_id,role", "limit": "10", **params}, timeout=_TIMEOUT)
        return r.json() if r.status_code == 200 else []
    roles = _roles_by({"auth_id": f"eq.{auth_id}"}) if auth_id else []
    if not roles and email:
        roles = _roles_by({"email": f"eq.{email.lower()}"})
    if not roles:
        # No calling-derived role yet — but a brand-new stake's FIRST enroller has no role until
        # the first sync provisions one. Fall back to the credential they just created (matched by
        # principal_email) so the app shows "setting up your stake", not the sign-in prompt (item 7).
        cred = _one("stake_credentials",
                    {"select": "stake_id,principal_name,revoked,coverage,updated_at",
                     "principal_email": f"eq.{email.lower()}", "limit": "1"})
        if cred:
            stake = _one("stakes", {"select": "name,unit_number,last_synced_at",
                                    "id": f"eq.{cred['stake_id']}", "limit": "1"}) or {}
            cov = cred.get("coverage") or {}
            # Real member count for the provider's stake (was hardcoded 0 → "Members 0" in settings
            # even when the stake is fully synced; the auth_id just didn't match a user_roles row).
            mc = _count_where("members", {"stake_id": f"eq.{cred['stake_id']}"}) or 0
            return {"status": "no_role", "stake_name": stake.get("name"),
                    "stake_id": cred["stake_id"], "unit_number": stake.get("unit_number"),
                    "last_synced_at": stake.get("last_synced_at"),
                    "member_count": mc, "has_data": mc > 0,
                    "credential": {
                        "state": "revoked" if cred.get("revoked") else "active",
                        "complete": bool(cov.get("complete")), "missing": cov.get("missing") or [],
                        "principal_name": cred.get("principal_name"), "is_provider": True,
                        "enrolled_at": cred.get("updated_at")}}
        # G (ADR-009 amendment): a no-role caller may be a RELEASED leader (or a member whose
        # calling never granted access) in a stake that IS synced. user_roles can no longer tell
        # us their stake — but the identity cache can. Return that stake's REAL state so the app
        # says "your calling doesn't grant access" instead of the misleading "your stake hasn't
        # set up Covenant Path yet". Only when a `stakes` row exists: a leader of a NEVER-enrolled
        # stake keeps the legacy payload (and the "set up stake sync" CTA). member_count is
        # deliberately omitted (least privilege for a no-role caller); email-OTP-only users have
        # no cache row and also keep the legacy payload.
        ident = _one("church_identities",
                     {"select": "unit_number,stake_name", "email": f"eq.{email.lower()}",
                      "unit_number": "not.is.null", "limit": "1"})
        if ident and ident.get("unit_number"):
            stake = _one("stakes", {"select": "id,name,unit_number,last_synced_at",
                                    "unit_number": f"eq.{ident['unit_number']}", "limit": "1"})
            if stake:
                cred2 = _one("stake_credentials", {"select": "revoked,last_failed_at",
                                                   "stake_id": f"eq.{stake['id']}", "limit": "1"})
                state = ("none" if not cred2
                         else "revoked" if cred2.get("revoked")
                         else "stale" if cred2.get("last_failed_at") else "active")
                return {"status": "no_role", "stake_name": stake.get("name"),
                        "stake_id": stake.get("id"), "unit_number": stake.get("unit_number"),
                        "last_synced_at": stake.get("last_synced_at"),
                        "member_count": 0, "has_data": False,
                        "credential": {"state": state}}
        return {"status": "no_role", "has_data": False, "credential": {"state": "none"}}
    stake_id = roles[0].get("stake_id")

    # 2. Get stake info
    stakes_r = requests.get(f"{SUPABASE_URL}/rest/v1/stakes", headers=headers,
                            params={"select": "name,unit_number,last_synced_at", "id": f"eq.{stake_id}",
                                    "limit": "1"}, timeout=_TIMEOUT)
    stake = (stakes_r.json() or [{}])[0] if stakes_r.status_code == 200 else {}

    # 3. Count members in this stake (service-role bypasses RLS — count all)
    members_r = requests.get(f"{SUPABASE_URL}/rest/v1/members",
                             headers={**headers, "Prefer": "count=exact", "Range": "0-0"},
                             params={"stake_id": f"eq.{stake_id}"}, timeout=_TIMEOUT)
    member_count = 0
    if members_r.status_code in (200, 206):
        cr = members_r.headers.get("Content-Range", "")
        if "/" in cr:
            total = cr.rsplit("/", 1)[-1]
            if total not in ("*", ""):
                member_count = int(total)

    # 3b. Patriarchal blessing is the ONE covenant-path field absent from the daily Member Tools sync
    # (covenant_path/membertools_adapter.py) — it only fills from the per-member LCR profile fetch during
    # a sync with a LIVE session, i.e. right after a re-auth. Count the REAL members (those with a real
    # baptism date → in the directory, profile-fetchable) still on the NEEDS_PROFILE sentinel, so the app
    # can offer a leader with profile access a "re-authorize to refresh" banner. Investigators (no profile
    # record, hence no baptism) are excluded so the count can actually reach zero.
    patriarchal_pending = _count_where("members", {
        "stake_id": f"eq.{stake_id}", "patriarchal_blessing": "eq.needs-profile-api",
        "and": "(baptism_date.not.is.null,baptism_date.neq.needs-profile-api)"}) or 0

    # 4. Get credential state
    cred_r = requests.get(f"{SUPABASE_URL}/rest/v1/stake_credentials", headers=headers,
                          params={"select": "principal_name,principal_email,revoked,coverage,access_rank,"
                                            "updated_at,last_failed_at,last_error",
                                  "stake_id": f"eq.{stake_id}", "limit": "1"}, timeout=_TIMEOUT)
    creds = cred_r.json() if cred_r.status_code == 200 else []
    cred = creds[0] if creds else None

    cred_info: dict
    if not cred:
        cred_info = {"state": "none"}
    else:
        coverage = cred.get("coverage") or {}
        # active / stale (last delegated sync failed — session needs re-auth) / revoked. The app shows a
        # "re-authorize" banner to the provider and a "sync failed — take over?" banner to other leaders.
        state = ("revoked" if cred.get("revoked")
                 else "stale" if cred.get("last_failed_at") else "active")
        cred_info = {
            "state": state,
            "complete": bool(coverage.get("complete")),
            "principal_name": cred.get("principal_name"),
            # Match on the stored email (principal_name is just a display name).
            "is_provider": (cred.get("principal_email") or "").lower() == email.lower(),
            # Can THIS credential's calling pull the patriarchal blessing flag (the member-profile
            # read)? Drives the "refresh patriarchal" banner alongside is_provider + patriarchal_pending.
            "can_refresh_patriarchal": "menu.view.member.profiles" in (coverage.get("features") or []),
            "enrolled_at": cred.get("updated_at"),
            "last_failed_at": cred.get("last_failed_at"),
            "last_error": cred.get("last_error"),
        }
    return {
        "stake_name": stake.get("name"),
        "stake_id": stake_id,
        "unit_number": stake.get("unit_number"),
        "last_synced_at": stake.get("last_synced_at"),
        "member_count": member_count,
        "has_data": member_count > 0,
        "patriarchal_pending": patriarchal_pending,
        "credential": cred_info,
    }


def revoke_credential(stake_id: str, email: str) -> dict:
    """Revoke the stake credential on behalf of the signed-in user.
    Only succeeds if the user is the active principal (is_provider check)."""
    headers = _sb_headers()
    # Verify the caller is actually the provider for this stake
    cred_r = requests.get(f"{SUPABASE_URL}/rest/v1/stake_credentials", headers=headers,
                          params={"select": "principal_email,revoked", "stake_id": f"eq.{stake_id}",
                                  "limit": "1"}, timeout=_TIMEOUT)
    creds = cred_r.json() if cred_r.status_code == 200 else []
    cred = creds[0] if creds else None
    if not cred:
        raise AdminError("no credential on file for this stake")
    if cred.get("revoked"):
        return {"status": "already_revoked"}
    if (cred.get("principal_email") or "").lower() != email.lower():
        raise NotAdmin("only the credential provider can revoke")
    return _patch_revoke(stake_id, headers)


def _patch_revoke(stake_id: str, headers: dict) -> dict:
    _cache_clear()  # the enrolled-stakes view must reflect the revoke immediately
    from datetime import datetime, timezone
    r = requests.patch(
        f"{SUPABASE_URL}/rest/v1/stake_credentials",
        headers={**headers, "Prefer": "return=minimal"},
        params={"stake_id": f"eq.{stake_id}"},
        json={"revoked": True, "revoked_at": datetime.now(timezone.utc).isoformat()},
        timeout=_TIMEOUT)
    if r.status_code >= 300:
        raise AdminError(f"revoke failed ({r.status_code}): {r.text[:160]}")
    return {"status": "revoked"}


def provider_stake_id(email: str) -> str | None:
    """The stake this user is the sync provider for — i.e. whose Drive they may connect (M7)."""
    cred = _one("stake_credentials",
                {"select": "stake_id", "principal_email": f"eq.{email.lower()}", "limit": "1"})
    return cred.get("stake_id") if cred else None


def get_schedule_for(email: str) -> dict:
    """The signed-in provider's stake sync schedule (in-app config, migration 0030). Defaults to
    7:00 ET / not paused when there's no stake_settings row yet."""
    sid = provider_stake_id(email)
    if not sid:
        return {"eligible": False}
    row = _one("stake_settings", {"select": "sync_hour_et,sync_paused", "stake_id": f"eq.{sid}",
                                  "limit": "1"}) or {}
    return {"eligible": True, "stake_id": sid,
            "hour_et": row.get("sync_hour_et", 7) if row.get("sync_hour_et") is not None else 7,
            "paused": bool(row.get("sync_paused", False))}


def set_schedule_for(email: str, hour_et: int, paused: bool) -> dict:
    """Upsert the provider's stake sync schedule. Validates the hour (0–23). Provider-gated."""
    sid = provider_stake_id(email)
    if not sid:
        raise NotAdmin("only the stake's sync provider can change the schedule")
    if not isinstance(hour_et, int) or not (0 <= hour_et <= 23):
        raise AdminError("hour_et must be an integer 0–23")
    r = requests.post(
        f"{SUPABASE_URL}/rest/v1/stake_settings",
        headers={**_sb_headers(), "Content-Type": "application/json",
                 "Prefer": "resolution=merge-duplicates,return=minimal"},
        json={"stake_id": sid, "sync_hour_et": hour_et, "sync_paused": bool(paused)},
        timeout=_TIMEOUT)
    if r.status_code >= 300:
        raise AdminError(f"could not save schedule ({r.status_code}): {r.text[:160]}")
    return {"hour_et": hour_et, "paused": bool(paused)}


def gdrive_status_for(email: str) -> dict:
    """Whether this user can connect Google Drive, and the current connection (M7). Includes the
    stake's spreadsheet link + last-sync time so the app can show actual usage, not just 'Connected'
    (item: 'I don't see the Drive syncing/usage')."""
    sid = provider_stake_id(email)
    if not sid:
        return {"eligible": False}
    s = _one("stakes", {"select": "gdrive_email,gdrive_connected_at,gdrive_file_id,gdrive_token,"
                                  "last_synced_at", "id": f"eq.{sid}", "limit": "1"}) or {}
    file_id = s.get("gdrive_file_id")
    connected = bool(s.get("gdrive_connected_at"))
    # A stale-token nudge: the daily sync clears gdrive_connected_at on a refresh failure but keeps
    # the token — so "not connected, yet a token is still on file" means "was connected, reconnect".
    needs_reconnect = (not connected) and bool(s.get("gdrive_token"))
    return {"eligible": True, "stake_id": sid,
            "connected": connected, "needs_reconnect": needs_reconnect,
            "email": s.get("gdrive_email"), "connected_at": s.get("gdrive_connected_at"),
            "file_id": file_id,
            "sheet_url": f"https://docs.google.com/spreadsheets/d/{file_id}" if file_id else None,
            "last_synced_at": s.get("last_synced_at")}


def store_gdrive_token(stake_id: str, encrypted_refresh: str, gdrive_email: str | None) -> dict:
    """Persist the envelope-encrypted Drive refresh token on the stake (M7 callback)."""
    from datetime import datetime, timezone
    r = requests.patch(
        f"{SUPABASE_URL}/rest/v1/stakes",
        headers={**_sb_headers(), "Prefer": "return=minimal"},
        params={"id": f"eq.{stake_id}"},
        json={"gdrive_token": encrypted_refresh, "gdrive_email": gdrive_email,
              "gdrive_connected_at": datetime.now(timezone.utc).isoformat()},
        timeout=_TIMEOUT)
    if r.status_code >= 300:
        raise AdminError(f"store gdrive token failed ({r.status_code}): {r.text[:120]}")
    return {"connected": True, "email": gdrive_email}


def disconnect_gdrive(stake_id: str) -> dict:
    r = requests.patch(
        f"{SUPABASE_URL}/rest/v1/stakes",
        headers={**_sb_headers(), "Prefer": "return=minimal"},
        params={"id": f"eq.{stake_id}"},
        json={"gdrive_token": None, "gdrive_email": None, "gdrive_connected_at": None,
              "gdrive_file_id": None},
        timeout=_TIMEOUT)
    if r.status_code >= 300:
        raise AdminError(f"disconnect failed ({r.status_code})")
    return {"connected": False}


def enrolled_stakes() -> list[dict]:
    """Every stake + its credential state + member count + freshness — the admin cross-stake
    ops view. Includes stakes with no credential (so admins see who still needs to enroll)."""
    return _cached("enrolled_stakes", 30, _enrolled_stakes)


_TOKEN_LIFETIME_DAYS = 45  # the Member Tools refresh token's ceiling (migration 0049)


def _token_days_left(minted_at: str | None, refresh_enc: str | None) -> int | None:
    """Days of life left in the 45-day Member Tools sync token: 45 − (days since minted). None when
    there's no token at all; can go negative (expired) so the ops view can flag it red."""
    if not refresh_enc or not minted_at:
        return None
    from datetime import datetime, timezone
    try:
        minted = datetime.fromisoformat(str(minted_at).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if minted.tzinfo is None:
        minted = minted.replace(tzinfo=timezone.utc)
    age_days = (datetime.now(timezone.utc) - minted).total_seconds() / 86400
    return _TOKEN_LIFETIME_DAYS - int(age_days)


def _enrolled_stakes() -> list[dict]:
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/stakes",
        headers=_sb_headers(),
        params={"select": "id,name,unit_number,last_synced_at,sync_state,onboarded_at,"
                          "stake_credentials(principal_name,principal_email,revoked,coverage,access_rank,"
                          "updated_at,last_failed_at,last_error,last_succeeded_at,has_refresh_token,"
                          "membertools_refresh_enc,membertools_minted_at)",
                "order": "name.asc"},
        timeout=_TIMEOUT)
    if r.status_code != 200:
        raise AdminError(f"could not list stakes ({r.status_code}): {r.text[:160]}")
    jobs = _jobs_last_7d()      # stake_id -> sync runs in the last 7 days (#9)
    counts = _member_counts()  # stake_id -> member count in ONE query (was N+1 → could hang the request)
    reauths = _reauths_30d()   # stake_unit -> re-authorizations in 30d (cadence visibility)
    out = []
    for s in r.json():
        # PostgREST returns a to-one embed as a JSON OBJECT (not a list) — `creds[0]` on a dict
        # would KeyError. Normalize to a list so a single stored credential still reads. (Same shape
        # bug that broke enroll._stored_credential_summary → the "always prompted to set up" issue.)
        sc = s.get("stake_credentials")
        creds = sc if isinstance(sc, list) else ([sc] if isinstance(sc, dict) else [])
        cred = creds[0] if creds else None
        cov = (cred or {}).get("coverage") or {}
        out.append({
            "stake_id": s["id"],
            "name": s.get("name"),
            "unit_number": s.get("unit_number"),
            "last_synced_at": s.get("last_synced_at"),
            "sync_state": s.get("sync_state"),
            "onboarded_at": s.get("onboarded_at"),
            "jobs_7d": jobs.get(s["id"], 0),
            "member_count": counts.get(s["id"], 0),
            "credential": None if not cred else {
                # active / stale (last delegated sync failed — needs re-auth) / revoked
                "state": ("revoked" if cred.get("revoked")
                          else "stale" if cred.get("last_failed_at") else "active"),
                "principal_name": cred.get("principal_name"),
                "principal_email": cred.get("principal_email"),
                "complete": bool(cov.get("complete")),
                "missing": cov.get("missing") or [],
                "access_rank": cred.get("access_rank"),
                "updated_at": cred.get("updated_at"),
                "last_failed_at": cred.get("last_failed_at"),
                "last_error": cred.get("last_error"),
                "last_succeeded_at": cred.get("last_succeeded_at"),
                # cadence: self-renewing means the daily sync can renew its own bearer for ~45 days
                # with no Okta web session. That now lives in the Member Tools refresh token
                # (migration 0049) — NOT the old LCR refresh token (has_refresh_token, ~always false),
                # which is what the chip used to read (it showed the OPPOSITE of the truth).
                "self_renewing": bool(cred.get("has_refresh_token"))
                                 or bool(cred.get("membertools_refresh_enc")),
                # When the 45-day Member Tools token was last minted + how many days of life it has
                # left (45 − age; null when no token). Drives the per-stake expiry countdown chip.
                "membertools_minted_at": cred.get("membertools_minted_at"),
                "token_expires_in_days": _token_days_left(
                    cred.get("membertools_minted_at"), cred.get("membertools_refresh_enc")),
                "reauths_30d": reauths.get(s.get("unit_number"), 0),
            },
        })
    return out


def admin_revoke_stake(stake_id: str) -> dict:
    """Admin override: revoke any stake's credential (no provider check). For ops support."""
    return _patch_revoke(stake_id, _sb_headers())


def send_reauth_email(stake_id: str) -> dict:
    """B3: on demand from the ops worklist, email the stake's credential PROVIDER the re-authorize
    nudge (the same day-40 body + /reauth deep link the daily sync sends near expiry). Looks up the
    provider email + stake name over REST (the broker holds no DB connection). NotFound (-> 404) when
    there's no credential / no provider email to send to."""
    cred = _one("stake_credentials",
                {"select": "principal_email,principal_name,revoked", "stake_id": f"eq.{stake_id}",
                 "limit": "1"})
    if not cred:
        raise NotFound("no credential on file for this stake")
    to = (cred.get("principal_email") or "").strip()
    if not to:
        raise NotFound("no provider email on file for this stake")
    stake = _one("stakes", {"select": "name,unit_number", "id": f"eq.{stake_id}", "limit": "1"}) or {}
    name = stake.get("name") or stake.get("unit_number") or "your stake"
    from html import escape  # BACKEND-02: escape the LCR-sourced stake name before the HTML body
    safe = escape(str(name))
    reauth_url = os.environ.get("APP_URL", "https://app.membercovenantpath.org").rstrip("/") + "/reauth"
    _send_email(
        to,
        f"Covenant Path — re-authorize the {safe} sync when convenient",
        (f"<p>The daily Covenant Path sync for <b>{safe}</b> needs to be re-authorized — the Church "
         f"session backing it has expired or is about to, and when it does the sync pauses until you "
         f"sign in again.</p>"
         f'<p style="margin:18px 0"><a href="{escape(reauth_url)}" '
         f'style="background:#7c5cff;color:#fff;padding:11px 20px;border-radius:8px;'
         f'text-decoration:none;font-weight:600">Re-authorize the {safe} sync</a></p>'
         f"<p>It takes under a minute — sign in once on the Church page (one verification code) and "
         f"the sync keeps running for another ~45 days. (You can also do it in the app → "
         f"<b>Sync settings → Re-authorize daily sync</b>.)</p>"))
    return {"status": "sent", "to": to, "stake": name}


def _rpc(name: str, params: dict) -> requests.Response:
    return requests.post(f"{SUPABASE_URL}/rest/v1/rpc/{name}",
                         headers={**_sb_headers(), "Content-Type": "application/json"},
                         json=params, timeout=_TIMEOUT)


def dispatch_stake_sync(stake_id: str, targets: str = "supabase") -> dict:
    """Trigger a sync for ONE stake — scoped via the workflow's `stake` input, never the full matrix."""
    s = _one("stakes", {"select": "unit_number", "id": f"eq.{stake_id}", "limit": "1"})
    if not s or not s.get("unit_number"):
        raise AdminError("no such stake")
    dispatch("daily-sync.yml", inputs={"stake": str(s["unit_number"]), "targets": targets})
    return {"status": "dispatched", "unit_number": s["unit_number"]}


def wipe_stake_data(stake_id: str) -> dict:
    """Delete a stake's MEMBER data (keeps the stake shell + roles + credential; re-populates on the
    next sync / re-enroll). 'Revoke + wipe data' tier."""
    _cache_clear()
    r = _rpc("wipe_stake_members", {"p_stake_id": stake_id})
    if r.status_code >= 300:
        raise AdminError(f"wipe failed ({r.status_code}): {r.text[:160]}")
    return {"status": "wiped", "deleted": (r.json() if r.text else None)}


def wipe_stake_data_as_provider(stake_id: str, email: str) -> dict:
    """Provider self-service tier of wipe_stake_data: the SAME wipe RPC, but gated to the
    credential's principal (mirrors revoke_credential). NotFound when the stake has no
    credential on file (-> 404); NotAdmin when the caller isn't the provider (-> 403)."""
    cred_r = requests.get(f"{SUPABASE_URL}/rest/v1/stake_credentials", headers=_sb_headers(),
                          params={"select": "principal_email", "stake_id": f"eq.{stake_id}",
                                  "limit": "1"}, timeout=_TIMEOUT)
    creds = cred_r.json() if cred_r.status_code == 200 else []
    cred = creds[0] if creds else None
    if not cred:
        raise NotFound("no credential on file for this stake")
    if (cred.get("principal_email") or "").lower() != email.lower():
        raise NotAdmin("only the credential provider can wipe stake data")
    return wipe_stake_data(stake_id)


def remove_stake(stake_id: str) -> dict:
    """FULL removal (admin only): credential + members + roles + diagnostics + the stake row, as if it
    never onboarded. Irreversible."""
    _cache_clear()
    r = _rpc("remove_stake", {"p_stake_id": stake_id})
    if r.status_code >= 300:
        raise AdminError(f"remove failed ({r.status_code}): {r.text[:160]}")
    return {"status": "removed", "stake_id": stake_id}


def summary() -> dict:
    """Row counts + data freshness from Supabase (service-role REST)."""
    return _cached("summary", 30, _summary)


def _summary() -> dict:
    last = _one("members", {"select": "updated_at", "order": "updated_at.desc", "limit": 1})
    stake = _one("stakes", {"select": "name,last_synced_at",
                            "order": "last_synced_at.desc.nullslast", "limit": 1})
    return {
        "ok": True,
        "members": _count("members"),
        "units": _count("units"),
        "stakes": _count("stakes"),
        "admins": _count("app_admins"),
        "last_member_update": (last or {}).get("updated_at"),
        "last_stake_sync": (stake or {}).get("last_synced_at"),
        "stake_name": (stake or {}).get("name"),
    }


# --- admin invitations (owner-approved) -------------------------------------

OWNER_EMAIL = os.environ.get("OWNER_EMAIL", "")  # approver + support inbox (set OWNER_EMAIL on the broker)
MAIL_FROM = os.environ.get("MAIL_FROM", "Covenant Path <noreply@membercovenantpath.org>")
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
BROKER_PUBLIC_URL = os.environ.get(
    "BROKER_PUBLIC_URL", "https://covenant-path-broker.onrender.com").rstrip("/")


def _send_email(to: str, subject: str, html: str) -> None:
    if not RESEND_API_KEY:
        raise AdminError("email not configured (RESEND_API_KEY)")
    r = requests.post("https://api.resend.com/emails",
                      headers={"Authorization": f"Bearer {RESEND_API_KEY}",
                               "Content-Type": "application/json"},
                      json={"from": MAIL_FROM, "to": [to], "subject": subject, "html": html},
                      timeout=_TIMEOUT)
    if r.status_code >= 300:
        raise AdminError(f"email send failed ({r.status_code}): {r.text[:160]}")


def send_contact(reporter: str, subject: str, message: str) -> dict:
    """Support / contact form (#74): email the owner a message from a signed-in user so they can
    follow up. Distinct from feedback→GitHub issue (#58) — this is a direct human support channel."""
    # collapse whitespace (incl. newlines) so the subject can't inject email headers; cap length.
    subject = " ".join((subject or "").split())[:140] or "Covenant Path — support request"
    body = (message or "").strip()
    if not body:
        raise AdminError("a message is required")
    # BACKEND-02: user-supplied reporter/subject/body must be HTML-escaped before entering the body.
    from html import escape
    html = (f"<h2>Support request</h2>"
            f"<p><b>From:</b> {escape(reporter)}</p>"
            f"<p><b>Subject:</b> {escape(subject)}</p>"
            f"<hr><p style='white-space:pre-wrap'>{escape(body)}</p>")
    _send_email(OWNER_EMAIL, f"[Covenant Path support] {subject}", html)
    return {"status": "sent", "to": OWNER_EMAIL}


def request_admin_invite(email: str, requested_by: str) -> dict:
    """Record a pending admin-invite + email the owner an approve link. Nobody is granted
    until the owner clicks it (the random token is the un-spoofable gate)."""
    import secrets as _secrets
    email = (email or "").strip().lower()
    if not email or "@" not in email:
        raise AdminError("a valid email is required")
    if _one("app_admins", {"select": "email", "email": f"eq.{email}"}):
        return {"status": "already_admin", "email": email}
    token = _secrets.token_urlsafe(32)
    r = requests.post(f"{SUPABASE_URL}/rest/v1/admin_invite_requests",
                      headers={**_sb_headers(), "Content-Type": "application/json"},
                      json={"email": email, "requested_by_email": requested_by,
                            "token": token, "status": "pending"}, timeout=_TIMEOUT)
    if r.status_code >= 300:
        raise AdminError(f"could not record request ({r.status_code}): {r.text[:160]}")
    link = f"{BROKER_PUBLIC_URL}/admin/approve?token={token}"
    from html import escape  # BACKEND-02: escape requester/email before the HTML body
    _send_email(OWNER_EMAIL, f"Approve admin access for {email}?",
                f"<p><b>{escape(requested_by)}</b> requested admin access for <b>{escape(email)}</b> on "
                f"Covenant Path.</p><p><a href=\"{escape(link)}\">Approve {escape(email)} as an admin</a></p>"
                f"<p>If you didn't expect this, ignore it — no access is granted unless you "
                f"click the link.</p>")
    return {"status": "pending_owner_approval", "email": email, "owner": OWNER_EMAIL}


def approve_admin_invite(token: str) -> dict:
    """Owner clicked the approve link → grant the admin (token-gated, idempotent)."""
    from datetime import datetime, timezone
    req = _one("admin_invite_requests",
               {"select": "id,email,requested_by_email,status", "token": f"eq.{(token or '').strip()}"})
    if not req:
        raise AdminError("invalid or expired approval link")
    if req["status"] != "pending":
        return {"status": req["status"], "email": req["email"]}
    email = req["email"]
    g = requests.post(f"{SUPABASE_URL}/rest/v1/app_admins",
                      headers={**_sb_headers(), "Content-Type": "application/json",
                               "Prefer": "resolution=merge-duplicates"},
                      json={"email": email, "invited_by_email": req.get("requested_by_email")},
                      timeout=_TIMEOUT)
    if g.status_code >= 300:
        raise AdminError(f"grant failed ({g.status_code}): {g.text[:160]}")
    requests.patch(f"{SUPABASE_URL}/rest/v1/admin_invite_requests",
                   headers={**_sb_headers(), "Content-Type": "application/json"},
                   params={"id": f"eq.{req['id']}"},
                   json={"status": "approved", "decided_at": datetime.now(timezone.utc).isoformat()},
                   timeout=_TIMEOUT)
    return {"status": "approved", "email": email}


# --- GitHub Actions ---------------------------------------------------------

def github_configured() -> bool:
    return bool(GITHUB_TOKEN)


def tool_links() -> dict:
    """External dashboards for the platform's services — admin-only (returned in /admin/summary,
    which is gated by require_admin). Only includes a link when its config is present."""
    links: dict[str, str] = {}
    if SUPABASE_URL:
        m = re.match(r"https://([a-z0-9-]+)\.supabase\.co", SUPABASE_URL)
        if m:
            links["Supabase"] = f"https://supabase.com/dashboard/project/{m.group(1)}"
    if GITHUB_REPO:
        links["GitHub repo"] = f"https://github.com/{GITHUB_REPO}"
        links["GitHub Actions"] = f"https://github.com/{GITHUB_REPO}/actions"
    sid = os.environ.get("SPREADSHEET_ID")
    if sid:
        links["Google Sheet"] = f"https://docs.google.com/spreadsheets/d/{sid}"
    app_url = os.environ.get("APP_URL")
    if app_url:
        links["App"] = app_url.rstrip("/")
    return links


def _gh_headers() -> dict:
    if not GITHUB_TOKEN:
        raise AdminError("github not configured (GITHUB_TOKEN)")
    return {"Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"}


def _parse_iso(s: str | None):
    """Parse a GitHub ISO-8601 timestamp ('...Z') to an aware datetime, or None."""
    from datetime import datetime
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _run_duration_seconds(w: dict):
    """Wall-clock execution time of a run, in whole seconds. For a finished run that's
    updated_at − run_started_at; for one still going it's now − run_started_at (a live elapsed),
    so the ops console can show a ticking timer. None when we can't tell yet."""
    from datetime import datetime, timezone
    start = _parse_iso(w.get("run_started_at") or w.get("created_at"))
    if not start:
        return None
    end = _parse_iso(w.get("updated_at")) if w.get("status") == "completed" \
        else datetime.now(timezone.utc)
    if not end:
        return None
    return max(0, int((end - start).total_seconds()))


def _run_dto(w: dict) -> dict:
    return {"id": w.get("id"), "name": w.get("name"), "status": w.get("status"),
            "conclusion": w.get("conclusion"), "event": w.get("event"),
            "run_number": w.get("run_number"), "created_at": w.get("created_at"),
            "run_started_at": w.get("run_started_at"),
            "updated_at": w.get("updated_at"),
            "duration_seconds": _run_duration_seconds(w),
            "html_url": w.get("html_url"),
            "workflow_path": (w.get("path") or "").split("/")[-1]}


def list_runs(limit: int = 15) -> list[dict]:
    def _fetch():
        r = requests.get(f"https://api.github.com/repos/{GITHUB_REPO}/actions/runs",
                         headers=_gh_headers(), params={"per_page": limit}, timeout=_TIMEOUT)
        r.raise_for_status()
        return [_run_dto(w) for w in r.json().get("workflow_runs", [])[:limit]]
    return _cached(f"runs:{limit}", 30, _fetch)


def run_status(run_id: int) -> dict:
    r = requests.get(f"https://api.github.com/repos/{GITHUB_REPO}/actions/runs/{run_id}",
                     headers=_gh_headers(), timeout=_TIMEOUT)
    r.raise_for_status()
    return _run_dto(r.json())


def dispatch(workflow: str, ref: str = "main", inputs: dict | None = None) -> None:
    if workflow not in DISPATCHABLE:
        raise AdminError(f"workflow not dispatchable: {workflow}")
    _cache_clear()  # a fresh run should appear on the next console read
    body: dict = {"ref": ref}
    if inputs:
        body["inputs"] = inputs
    r = requests.post(
        f"https://api.github.com/repos/{GITHUB_REPO}/actions/workflows/{workflow}/dispatches",
        headers=_gh_headers(), json=body, timeout=_TIMEOUT)
    if r.status_code not in (201, 204):
        raise AdminError(f"dispatch failed ({r.status_code}): {r.text[:200]}")


def rerun(run_id: int) -> None:
    r = requests.post(
        f"https://api.github.com/repos/{GITHUB_REPO}/actions/runs/{run_id}/rerun",
        headers=_gh_headers(), timeout=_TIMEOUT)
    if r.status_code not in (201, 204):
        raise AdminError(f"rerun failed ({r.status_code}): {r.text[:200]}")


def _sanitize_issue_text(s: str, limit: int) -> str:
    """Neutralize user-submitted feedback before it becomes a GitHub issue. Issues don't execute
    anything, but unsanitized text can mass-ping people (@mentions), cross-link/auto-close issues
    (#123, "fixes #..."), or smuggle control chars. We cap length, drop control chars (keep \\n/\\t),
    and defang @ / # by inserting a zero-width space so they render literally but don't trigger
    GitHub. We never auto-merge or run anything from feedback — it only ever opens an issue."""
    s = (s or "").strip()[:limit]
    s = "".join(ch for ch in s if ch in "\n\t" or ord(ch) >= 0x20)
    s = re.sub(r"([@#])(?=\w)", "\\1​", s)          # @mention / #ref -> inert
    s = re.sub(r"(?i)\b(close[sd]?|fix(e[sd])?|resolve[sd]?)(?=\s+#?​?\d)",
               r"\1​", s)                            # defang "fixes #123" auto-close keywords
    return s


def create_feedback_issue(title: str, body: str, reporter: str) -> dict:
    """File a GitHub issue from in-app feedback and best-effort hand it to Copilot's coding
    agent. Requires the broker PAT to have Issues: write. Copilot assignment is optional —
    the issue is filed regardless (auto-assign needs Copilot enabled on the repo).

    Input is sanitized (see _sanitize_issue_text). This NEVER merges anything: at most it opens an
    issue and assigns Copilot, which can only PROPOSE a PR — a human still reviews and merges."""
    if not GITHUB_TOKEN:
        raise AdminError("github not configured (GITHUB_TOKEN)")
    title = _sanitize_issue_text(title, 120).replace("\n", " ") or "App feedback"
    safe_body = _sanitize_issue_text(body, 8000)
    full = f"{safe_body}\n\n— filed via Covenant Path by `{reporter}`"
    r = requests.post(f"https://api.github.com/repos/{GITHUB_REPO}/issues", headers=_gh_headers(),
                      json={"title": title, "body": full, "labels": ["feedback"]}, timeout=_TIMEOUT)
    if r.status_code >= 300:
        raise AdminError(f"issue create failed ({r.status_code}): {r.text[:160]}")
    issue = r.json()
    num, url = issue.get("number"), issue.get("html_url")
    copilot = False
    assignee = os.environ.get("COPILOT_ASSIGNEE", "copilot-swe-agent")
    try:  # best-effort — ignore if the Copilot agent login isn't assignable on this repo
        a = requests.post(f"https://api.github.com/repos/{GITHUB_REPO}/issues/{num}/assignees",
                          headers=_gh_headers(), json={"assignees": [assignee]}, timeout=_TIMEOUT)
        copilot = a.status_code < 300 and any(
            (x.get("login") or "").lower().startswith("copilot")
            for x in (a.json().get("assignees") or []))
    except requests.RequestException:
        pass
    return {"number": num, "url": url, "copilot": copilot}


def recent_commits(limit: int = 10) -> list[dict]:
    def _fetch():
        r = requests.get(f"https://api.github.com/repos/{GITHUB_REPO}/commits",
                         headers=_gh_headers(), params={"per_page": limit}, timeout=_TIMEOUT)
        r.raise_for_status()
        out = []
        for c in r.json()[:limit]:
            commit = c.get("commit", {})
            out.append({"sha": (c.get("sha") or "")[:7],
                        "message": (commit.get("message") or "").splitlines()[0],
                        "author": (commit.get("author") or {}).get("name"),
                        "date": (commit.get("author") or {}).get("date"),
                        "html_url": c.get("html_url")})
        return out
    return _cached(f"commits:{limit}", 60, _fetch)
