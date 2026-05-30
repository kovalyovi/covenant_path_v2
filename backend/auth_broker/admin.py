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


def recent_diagnostics(limit: int = 12) -> list[dict]:
    """Recent sync/probe diagnostics rows (latest first)."""
    try:
        r = requests.get(f"{SUPABASE_URL}/rest/v1/sync_diagnostics", headers=_sb_headers(),
                         params={"select": "run_at,kind,stake_id,payload",
                                 "order": "run_at.desc", "limit": limit}, timeout=_TIMEOUT)
    except requests.RequestException:
        return []
    return r.json() if r.status_code == 200 else []


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
    # 1. Find user's role → stake_id
    roles_r = requests.get(f"{SUPABASE_URL}/rest/v1/user_roles", headers=headers,
                           params={"select": "stake_id,role", "auth_id": f"eq.{auth_id}",
                                   "limit": "10"}, timeout=_TIMEOUT)
    roles = roles_r.json() if roles_r.status_code == 200 else []
    if not roles:
        # No calling-derived role yet — but a brand-new stake's FIRST enroller has no role until
        # the first sync provisions one. Fall back to the credential they just created (matched by
        # principal_email) so the app shows "setting up your stake", not the sign-in prompt (item 7).
        cred = _one("stake_credentials",
                    {"select": "stake_id,principal_name,revoked,coverage,updated_at",
                     "principal_email": f"eq.{email.lower()}", "limit": "1"})
        if cred:
            stake = _one("stakes", {"select": "name,last_synced_at",
                                    "id": f"eq.{cred['stake_id']}", "limit": "1"}) or {}
            cov = cred.get("coverage") or {}
            return {"status": "no_role", "stake_name": stake.get("name"),
                    "stake_id": cred["stake_id"], "last_synced_at": stake.get("last_synced_at"),
                    "member_count": 0, "has_data": False,
                    "credential": {
                        "state": "revoked" if cred.get("revoked") else "active",
                        "complete": bool(cov.get("complete")), "missing": cov.get("missing") or [],
                        "principal_name": cred.get("principal_name"), "is_provider": True,
                        "enrolled_at": cred.get("updated_at")}}
        return {"status": "no_role", "has_data": False, "credential": {"state": "none"}}
    stake_id = roles[0].get("stake_id")

    # 2. Get stake info
    stakes_r = requests.get(f"{SUPABASE_URL}/rest/v1/stakes", headers=headers,
                            params={"select": "name,last_synced_at", "id": f"eq.{stake_id}",
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

    # 4. Get credential state
    cred_r = requests.get(f"{SUPABASE_URL}/rest/v1/stake_credentials", headers=headers,
                          params={"select": "principal_name,principal_email,revoked,coverage,access_rank,updated_at",
                                  "stake_id": f"eq.{stake_id}", "limit": "1"}, timeout=_TIMEOUT)
    creds = cred_r.json() if cred_r.status_code == 200 else []
    cred = creds[0] if creds else None

    cred_info: dict
    if not cred:
        cred_info = {"state": "none"}
    else:
        coverage = cred.get("coverage") or {}
        cred_info = {
            "state": "revoked" if cred.get("revoked") else "active",
            "complete": bool(coverage.get("complete")),
            "principal_name": cred.get("principal_name"),
            # Match on the stored email (principal_name is just a display name).
            "is_provider": (cred.get("principal_email") or "").lower() == email.lower(),
            "enrolled_at": cred.get("updated_at"),
        }
    return {
        "stake_name": stake.get("name"),
        "stake_id": stake_id,
        "last_synced_at": stake.get("last_synced_at"),
        "member_count": member_count,
        "has_data": member_count > 0,
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


def enrolled_stakes() -> list[dict]:
    """Every stake + its credential state + member count + freshness — the admin cross-stake
    ops view. Includes stakes with no credential (so admins see who still needs to enroll)."""
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/stakes",
        headers=_sb_headers(),
        params={"select": "id,name,unit_number,last_synced_at,sync_state,onboarded_at,"
                          "stake_credentials(principal_name,revoked,coverage,access_rank,updated_at)",
                "order": "name.asc"},
        timeout=_TIMEOUT)
    if r.status_code != 200:
        raise AdminError(f"could not list stakes ({r.status_code}): {r.text[:160]}")
    out = []
    for s in r.json():
        creds = s.get("stake_credentials") or []
        cred = creds[0] if creds else None
        cov = (cred or {}).get("coverage") or {}
        out.append({
            "stake_id": s["id"],
            "name": s.get("name"),
            "unit_number": s.get("unit_number"),
            "last_synced_at": s.get("last_synced_at"),
            "sync_state": s.get("sync_state"),
            "onboarded_at": s.get("onboarded_at"),
            "member_count": _count_where("members", {"stake_id": f"eq.{s['id']}"}) or 0,
            "credential": None if not cred else {
                "state": "revoked" if cred.get("revoked") else "active",
                "principal_name": cred.get("principal_name"),
                "complete": bool(cov.get("complete")),
                "missing": cov.get("missing") or [],
                "access_rank": cred.get("access_rank"),
                "updated_at": cred.get("updated_at"),
            },
        })
    return out


def admin_revoke_stake(stake_id: str) -> dict:
    """Admin override: revoke any stake's credential (no provider check). For ops support."""
    return _patch_revoke(stake_id, _sb_headers())


def summary() -> dict:
    """Row counts + data freshness from Supabase (service-role REST)."""
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

OWNER_EMAIL = os.environ.get("OWNER_EMAIL", "ilia.kovaliov@gmail.com")  # approver + support inbox
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
    subject = (subject or "").strip()[:140] or "Covenant Path — support request"
    body = (message or "").strip()
    if not body:
        raise AdminError("a message is required")
    html = (f"<h2>Support request</h2>"
            f"<p><b>From:</b> {reporter}</p>"
            f"<p><b>Subject:</b> {subject}</p>"
            f"<hr><p style='white-space:pre-wrap'>{body}</p>")
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
    _send_email(OWNER_EMAIL, f"Approve admin access for {email}?",
                f"<p><b>{requested_by}</b> requested admin access for <b>{email}</b> on "
                f"Covenant Path.</p><p><a href=\"{link}\">Approve {email} as an admin</a></p>"
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
    import re
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


def _run_dto(w: dict) -> dict:
    return {"id": w.get("id"), "name": w.get("name"), "status": w.get("status"),
            "conclusion": w.get("conclusion"), "event": w.get("event"),
            "run_number": w.get("run_number"), "created_at": w.get("created_at"),
            "updated_at": w.get("updated_at"), "html_url": w.get("html_url"),
            "workflow_path": (w.get("path") or "").split("/")[-1]}


def list_runs(limit: int = 15) -> list[dict]:
    r = requests.get(f"https://api.github.com/repos/{GITHUB_REPO}/actions/runs",
                     headers=_gh_headers(), params={"per_page": limit}, timeout=_TIMEOUT)
    r.raise_for_status()
    return [_run_dto(w) for w in r.json().get("workflow_runs", [])[:limit]]


def run_status(run_id: int) -> dict:
    r = requests.get(f"https://api.github.com/repos/{GITHUB_REPO}/actions/runs/{run_id}",
                     headers=_gh_headers(), timeout=_TIMEOUT)
    r.raise_for_status()
    return _run_dto(r.json())


def dispatch(workflow: str, ref: str = "main", inputs: dict | None = None) -> None:
    if workflow not in DISPATCHABLE:
        raise AdminError(f"workflow not dispatchable: {workflow}")
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


def create_feedback_issue(title: str, body: str, reporter: str) -> dict:
    """File a GitHub issue from in-app feedback and best-effort hand it to Copilot's coding
    agent. Requires the broker PAT to have Issues: write. Copilot assignment is optional —
    the issue is filed regardless (auto-assign needs Copilot enabled on the repo)."""
    if not GITHUB_TOKEN:
        raise AdminError("github not configured (GITHUB_TOKEN)")
    title = (title or "").strip()[:120] or "App feedback"
    full = f"{(body or '').strip()}\n\n— filed via Covenant Path by {reporter}"
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
