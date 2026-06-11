"""
Member Tools mobile API — the RELIABLE bulk source.

`POST https://membertools-api.churchofjesuschrist.org/api/v5/sync` returns the WHOLE stake in one
~7MB call: the covenant-path / convert-progress data (lessons, baptism goal, commitments, friends,
attendance, sealing), plus temple recommends, ministering, households, missionaries, unit stats. It
replaces the fragile `/api/report/one-work/*` cluster (progress-record + per-person details) that
takes multi-hour outages — see docs/SYNC_PACING_PLAN.md and the rate-finder characterization.

Auth is an OAuth **bearer** (the LCR appSession cookie is rejected here): a token minted from the
Member Tools **public** Okta client via Authorization-Code + PKCE. Two ways in:
  • `mint_from_okta_session(session)` — SILENT (`prompt=none`) authorize against a LIVE Okta session
    (the `sid` set during our normal Church login, in okta_login._authenticate_okta). No 2nd sign-in.
    Returns {access_token, refresh_token, ...}. The refresh_token is good for **45 days** (non-rotating,
    non-extendable) → store it and renew access tokens off it for the daily sync, no re-login needed.
  • `refresh(refresh_token)` — renew a 24h access token from the stored refresh token, NO session.

Recipe reverse-engineered + verified from github.com/rickybloomfield/Mission-KPIs (MemberToolsAuth.swift,
MemberToolsClient.swift, docs/auth.md) and tools/membertools_probe.py (live mint + sync confirmed).
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from urllib.parse import urlparse, parse_qs

import requests

from lcr_client.logging_setup import get_logger

logger = get_logger()

OKTA = "https://id.churchofjesuschrist.org/oauth2/default/v1"
API_BASE = "https://membertools-api.churchofjesuschrist.org"
SYNC_URL = f"{API_BASE}/api/v5/sync"
SYNC_FILES_URL = f"{API_BASE}/api/v5/sync/files"

CLIENT_ID = "0oa18r3fbarSYzU4V358"          # Member Tools PUBLIC client (token_endpoint_auth_method: none)
REDIRECT_URI = "membertoolsauth://login"
SCOPE = "openid profile offline_access cmisid no_links"
USER_AGENT = "MLTools 5.5.2-(13763) / iOS 17.0 / iPhone"

# The app's manual-sync body. An empty {} returns a DEGRADED payload missing name fields, so always
# send this (timeZone is cosmetic; the server doesn't gate on it).
SYNC_BODY = {"manual": True, "automatic": True, "attempt": 1, "timeZone": "America/New_York"}

REFRESH_TOKEN_LIFETIME_DAYS = 45             # absolute, non-rotating (docs/auth.md, /introspect-verified)


class MemberToolsError(RuntimeError):
    """A Member Tools auth/fetch failure."""


class RefreshTokenExpired(MemberToolsError):
    """The refresh token is permanently dead (45-day cap or revoked) → re-login required."""


# --- PKCE ----------------------------------------------------------------------------------------

def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _pkce() -> tuple[str, str]:
    verifier = _b64url(secrets.token_bytes(32))
    challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
    return verifier, challenge


def _token_request(form: dict) -> dict:
    """POST the Okta /token endpoint. Raises RefreshTokenExpired on invalid_grant, MemberToolsError
    otherwise; returns the token JSON on success."""
    r = requests.post(f"{OKTA}/token", data=form, timeout=60,
                      headers={"User-Agent": USER_AGENT, "Accept": "application/json",
                               "Content-Type": "application/x-www-form-urlencoded"})
    if r.status_code >= 400:
        try:
            err = r.json()
        except ValueError:
            err = {}
        if err.get("error") == "invalid_grant":
            raise RefreshTokenExpired(err.get("error_description") or "invalid_grant")
        raise MemberToolsError(f"token endpoint {r.status_code}: {str(err) or r.text[:160]}")
    return r.json()


# --- mint / refresh ------------------------------------------------------------------------------

def mint_from_okta_session(session: requests.Session) -> dict:
    """Silently mint a Member Tools token using the LIVE Okta session already in `session`'s cookie
    jar (the `sid` from a fresh okta_login._authenticate_okta). Returns the token dict
    {access_token, refresh_token, expires_in, scope, ...}. Raises MemberToolsError if the Okta session
    isn't live (the silent authorize returns error=login_required instead of a code)."""
    verifier, challenge = _pkce()
    params = {
        "client_id": CLIENT_ID, "redirect_uri": REDIRECT_URI, "response_type": "code", "scope": SCOPE,
        "code_challenge": challenge, "code_challenge_method": "S256",
        "state": secrets.token_hex(8), "nonce": secrets.token_hex(8), "prompt": "none",
    }
    r = session.get(f"{OKTA}/authorize", params=params, allow_redirects=False, timeout=60,
                    headers={"User-Agent": USER_AGENT,
                             "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"})
    # The redirect target is the custom scheme membertoolsauth://login?code=… — requests can't follow
    # it, so read the Location header directly. A 200 (HTML) or error= means the silent SSO didn't take.
    loc = r.headers.get("Location", "")
    if not (300 <= r.status_code < 400) or "code=" not in loc:
        q = parse_qs(urlparse(loc).query) if loc else {}
        raise MemberToolsError(
            f"silent authorize did not return a code (HTTP {r.status_code}, "
            f"error={q.get('error', ['none'])[0]}) — Okta session not live")
    code = parse_qs(urlparse(loc).query)["code"][0]
    tok = _token_request({
        "grant_type": "authorization_code", "client_id": CLIENT_ID, "code": code,
        "code_verifier": verifier, "redirect_uri": REDIRECT_URI,
    })
    logger.info("Member Tools token minted (expires_in=%s, refresh=%s)",
                tok.get("expires_in"), bool(tok.get("refresh_token")))
    return tok


def refresh(refresh_token: str) -> dict:
    """Renew a 24h access token from a stored refresh token — no Okta session needed. Rotation is OFF
    so the SAME refresh_token stays valid (preserve its original mint date for the 45-day clock).
    Raises RefreshTokenExpired when the refresh token has hit the 45-day wall / been revoked."""
    return _token_request({
        "grant_type": "refresh_token", "client_id": CLIENT_ID,
        "refresh_token": refresh_token, "scope": SCOPE,
    })


# --- bulk fetch ----------------------------------------------------------------------------------

def fetch_sync(access_token: str, *, timeout: float = 180.0) -> dict:
    """The whole-stake bulk pull. Returns the parsed JSON (~7MB) with covenantPath* + everything."""
    r = requests.post(SYNC_URL, data=json.dumps(SYNC_BODY), timeout=timeout,
                      headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json",
                               "Content-Type": "application/json", "Accept-Language": "en-US,en;q=0.9",
                               "User-Agent": USER_AGENT})
    if r.status_code == 401:
        raise MemberToolsError("/api/v5/sync 401 — access token expired/invalid")
    r.raise_for_status()
    return r.json()
