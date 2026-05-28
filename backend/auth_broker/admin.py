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


def verify_admin(authorization: str) -> str:
    """`authorization` = the app user's "Bearer <supabase access token>". Returns the
    admin's email, or raises NotAdmin / AdminError. The token is verified by GoTrue;
    admin membership is checked against app_admins with the service-role key."""
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


def recent_diagnostics(limit: int = 12) -> list[dict]:
    """Recent sync/probe diagnostics rows (latest first)."""
    try:
        r = requests.get(f"{SUPABASE_URL}/rest/v1/sync_diagnostics", headers=_sb_headers(),
                         params={"select": "run_at,kind,stake_id,payload",
                                 "order": "run_at.desc", "limit": limit}, timeout=_TIMEOUT)
    except requests.RequestException:
        return []
    return r.json() if r.status_code == 200 else []


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
