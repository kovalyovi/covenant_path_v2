"""
Zero-browser LCR login via the Okta Identity Engine (IDX) interaction-code flow.

Replicates, in plain `requests`, the login flow captured from the browser so the
whole pipeline can run without Playwright (e.g. in GitHub Actions). Strategy is
two-phase and deliberately decoupled from LCR's own PKCE:

  Phase 1 — authenticate to Okta (establish the org-wide Okta session cookie):
    POST {issuer}/v1/interact          (throwaway PKCE) -> interaction_handle
    POST /idp/idx/introspect           {interactionHandle} -> stateHandle + remediations
    POST /idp/idx/identify             {identifier}
    POST /idp/idx/challenge            {authenticator:{id}}   (select password)
    POST /idp/idx/challenge/answer     {credentials:{passcode}} -> successWithInteractionCode
  The IDX transaction sets the Okta session cookie on id.churchofjesuschrist.org.

  Phase 2 — let LCR's auth handler mint its session cookies via SSO:
    GET  lcr /api/auth/login?returnTo=/  (sets LCR's own state/PKCE cookie)
      -> 302 Okta /authorize  (Okta session present -> issues code, no prompt)
      -> 302 lcr /api/auth/callback?code=...  (LCR exchanges code server-side)
      -> 302 lcr /                          (LCR session cookies set)

Result: the requests cookie jar holds the LCR session, written out as a
Playwright-compatible `storage_state.json` that `LcrSession` consumes unchanged.

SECURITY: the password is read from env (LCR_PASSWORD) or passed in, placed only
in the IDX answer body, and NEVER logged or persisted. IDX error `messages` are
surfaced (they never contain the password).

Usage:
  python -m lcr_client.okta_login            # uses LCR_LOGIN / LCR_PASSWORD from .env
  from lcr_client.okta_login import login; login()
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
from pathlib import Path
from typing import Any

import requests

from lcr_client.logging_setup import dump_debug, get_logger

logger = get_logger()

ORG = "https://id.churchofjesuschrist.org"
ISSUER = f"{ORG}/oauth2/default"
INTROSPECT_URL = f"{ORG}/idp/idx/introspect"
LCR = "https://lcr.churchofjesuschrist.org"

# Public SPA client config (captured from the live login flow; not secret).
CLIENT_ID = "0oajwqqtpz7f8r1OD357"
SCOPE = "openid profile email offline_access cmisid group"
REDIRECT_URI = f"{LCR}/api/auth/callback"
# Fallback password-authenticator id if option parsing can't find it.
PASSWORD_AUTHENTICATOR_ID = "aut11a6qzu9GG54WD358"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36"
)
IDX_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json; okta-version=1.0.0",
}
DEFAULT_STORAGE_STATE = (
    Path(__file__).resolve().parent.parent / "tools" / "output" / "storage_state.json"
)


class LoginError(RuntimeError):
    """Raised when the headless Okta/LCR login cannot complete."""


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _pkce() -> tuple[str, str]:
    verifier = _b64url(secrets.token_bytes(32))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def _idx_messages(payload: dict) -> str:
    """Pull human-readable error text out of an IDX response (no secrets)."""
    msgs = payload.get("messages", {}).get("value", []) if isinstance(payload, dict) else []
    return "; ".join(m.get("message", "") for m in msgs) or json.dumps(payload)[:300]


def _idx_post(session: requests.Session, url: str, body: dict, *, redact: bool = False) -> dict:
    resp = session.post(url, json=body, headers=IDX_HEADERS, timeout=60)
    try:
        payload = resp.json()
    except ValueError:
        payload = {}
    if resp.status_code >= 400:
        # Never echo `body` here — it may carry the passcode.
        logger.error("IDX %s -> %s: %s", url.rsplit("/", 1)[-1], resp.status_code,
                     _idx_messages(payload))
        if not redact:
            dump_debug("idx_error", url=url, status=resp.status_code, body=payload)
        raise LoginError(f"IDX step {url.rsplit('/', 1)[-1]} failed: {_idx_messages(payload)}")
    return payload


def _remediations(payload: dict) -> dict[str, dict]:
    return {r["name"]: r for r in payload.get("remediation", {}).get("value", [])}


def _follow(session: requests.Session, remediation: dict, body: dict, *, redact: bool = False) -> dict:
    """POST a remediation to its own href (self-adapting to LCR/Okta changes)."""
    body = {**body, "stateHandle": remediation.get("_stateHandle")}
    return _idx_post(session, remediation["href"], body, redact=redact)


def _password_authenticator_id(remediation: dict) -> str:
    for field in remediation.get("value", []):
        if field.get("name") != "authenticator":
            continue
        for opt in field.get("options", []):
            if "password" not in opt.get("label", "").lower():
                continue
            form_vals = opt.get("value", {}).get("form", {}).get("value", [])
            id_field = next((f for f in form_vals if f.get("name") == "id"), None)
            if id_field and id_field.get("value"):
                return id_field["value"]
    logger.warning("password authenticator id not found in options; using fallback")
    return PASSWORD_AUTHENTICATOR_ID


def _authenticate_okta(session: requests.Session, identifier: str, password: str) -> None:
    """Phase 1: complete the IDX transaction to establish the Okta session cookie."""
    verifier, challenge = _pkce()
    state = secrets.token_hex(16)

    logger.info("okta interact (interaction-code bootstrap)")
    interact = session.post(
        f"{ISSUER}/v1/interact",
        data={
            "client_id": CLIENT_ID,
            "scope": SCOPE,
            "redirect_uri": REDIRECT_URI,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded",
                 "Accept": "application/json"},
        timeout=60,
    )
    if interact.status_code >= 400:
        dump_debug("interact_error", status=interact.status_code, body=interact.text[:500])
        raise LoginError(f"interact failed: {interact.status_code} {interact.text[:200]}")
    interaction_handle = interact.json()["interaction_handle"]

    logger.info("okta introspect")
    payload = _idx_post(session, INTROSPECT_URL, {"interactionHandle": interaction_handle})

    identified = selected = False
    for _ in range(8):
        if "successWithInteractionCode" in payload:
            logger.info("okta IDX success (session established)")
            return
        rems = _remediations(payload)
        state_handle = payload.get("stateHandle")
        for r in rems.values():
            r["_stateHandle"] = state_handle

        if not identified and "identify" in rems:
            logger.info("okta identify")
            payload = _follow(session, rems["identify"],
                              {"identifier": identifier, "rememberMe": False})
            identified = True
            continue
        if "challenge-authenticator" in rems:
            logger.info("okta challenge/answer (password)")
            payload = _follow(session, rems["challenge-authenticator"],
                              {"credentials": {"passcode": password}}, redact=True)
            continue
        if not selected and "select-authenticator-authenticate" in rems:
            aid = _password_authenticator_id(rems["select-authenticator-authenticate"])
            logger.info("okta select password authenticator")
            payload = _follow(session, rems["select-authenticator-authenticate"],
                              {"authenticator": {"id": aid}})
            selected = True
            continue
        dump_debug("idx_stuck", remediations=sorted(rems))
        raise LoginError(f"Unexpected IDX state; remediations={sorted(rems)}")
    raise LoginError("IDX flow did not reach success within step budget")


def _establish_lcr_session(session: requests.Session) -> None:
    """Phase 2: SSO through LCR's auth handler to mint the LCR session cookies."""
    logger.info("lcr /api/auth/login (SSO via existing Okta session)")
    resp = session.get(f"{LCR}/api/auth/login", params={"returnTo": "/"},
                       allow_redirects=True, timeout=60)
    host = requests.utils.urlparse(resp.url).hostname or ""
    if host.startswith("id."):
        dump_debug("lcr_sso_failed", final_url=resp.url, status=resp.status_code)
        raise LoginError(
            "SSO did not complete — landed back on Okta. The Okta session cookie "
            "was not honored by /authorize."
        )


def _write_storage_state(session: requests.Session, path: Path) -> int:
    cookies = []
    for c in session.cookies:
        if "churchofjesuschrist.org" not in (c.domain or ""):
            continue
        cookies.append({
            "name": c.name,
            "value": c.value,
            "domain": c.domain,
            "path": c.path or "/",
            "expires": float(c.expires) if c.expires else -1,
            "httpOnly": bool(c._rest.get("HttpOnly")) if hasattr(c, "_rest") else False,
            "secure": bool(c.secure),
            "sameSite": "Lax",
        })
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"cookies": cookies, "origins": []}, indent=2),
                    encoding="utf-8")
    return len(cookies)


def _verify(session: requests.Session) -> dict[str, Any]:
    resp = session.get(f"{LCR}/api/auth/me", params={"lang": "eng"}, timeout=60)
    ctype = resp.headers.get("content-type", "")
    if resp.status_code != 200 or "application/json" not in ctype:
        raise LoginError(f"verification /api/auth/me failed: {resp.status_code} {ctype}")
    return resp.json()


# --- reusable building blocks (shared with delegated_login) ------------------

def new_session() -> requests.Session:
    """A bare requests.Session with the browser-like User-Agent we use everywhere."""
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    return s


def session_from_cookies(cookies: list[dict]) -> requests.Session:
    """Build a session seeded with stored cookies (name/value/domain/path dicts)."""
    s = new_session()
    for c in cookies:
        s.cookies.set(c["name"], c["value"], domain=c.get("domain"), path=c.get("path", "/"))
    return s


def establish_lcr_session(session: requests.Session) -> None:
    """Public: SSO through LCR to (re)mint LCR session cookies (Okta session must be live)."""
    _establish_lcr_session(session)


def write_storage_state(session: requests.Session, path: str | Path) -> int:
    """Public: persist the session's churchofjesuschrist.org cookies as storage_state.json."""
    return _write_storage_state(session, Path(path))


def verify_session(session: requests.Session) -> dict[str, Any]:
    """Public: confirm the session is an authenticated LCR session; returns /api/auth/me."""
    return _verify(session)


def try_silent_sso(session: requests.Session, id_token: str) -> bool:
    """Re-establish an LCR session via OAuth prompt=none with id_token_hint — no MFA needed.
    Intercepts LCR's auth redirect, adds prompt=none+id_token_hint, follows back to LCR.
    Returns True if new LCR session cookies were set, False on any failure (never raises)."""
    try:
        from urllib.parse import parse_qs, urlencode, urlparse, urlunparse
        resp1 = session.get(f"{LCR}/api/auth/login", params={"returnTo": "/"},
                            allow_redirects=False, timeout=30)
        if resp1.status_code not in (301, 302, 303, 307, 308):
            return False
        okta_url = resp1.headers.get("Location", "")
        if not okta_url or "id.churchofjesuschrist.org" not in okta_url:
            return False
        parsed = urlparse(okta_url)
        params = {k: v[0] for k, v in parse_qs(parsed.query, keep_blank_values=True).items()}
        params.update({"prompt": "none", "id_token_hint": id_token})
        new_url = urlunparse(parsed._replace(query=urlencode(params)))
        resp2 = session.get(new_url, allow_redirects=True, timeout=60)
        final_host = urlparse(resp2.url).hostname or ""
        if final_host.startswith("id."):
            return False  # still on Okta — SSO didn't complete
        logger.info("silent SSO succeeded via id_token_hint")
        return True
    except Exception as exc:  # noqa: BLE001
        logger.info("silent SSO failed (non-fatal): %s", exc)
        return False


def try_refresh_session(session: requests.Session, refresh_token: str | None) -> bool:
    """Renew an expired LCR session using a stored OAuth refresh_token. Exchanges the
    refresh_token for a new id_token, then attempts silent SSO to get fresh LCR cookies.
    Returns True only if verify_session would now succeed, False on any failure (never raises)."""
    if not refresh_token:
        return False
    try:
        resp = session.post(f"{ISSUER}/v1/token", data={
            "grant_type": "refresh_token",
            "client_id": CLIENT_ID,
            "refresh_token": refresh_token,
            "scope": SCOPE,
        }, headers={"Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json"}, timeout=30)
        if resp.status_code != 200:
            logger.info("refresh_token exchange failed (%s) — credential needs re-enrollment",
                        resp.status_code)
            return False
        tokens = resp.json()
        id_token = tokens.get("id_token")
        if not id_token:
            logger.info("refresh_token exchange returned no id_token")
            return False
        if not try_silent_sso(session, id_token):
            logger.info("silent SSO after token refresh failed — credential needs re-enrollment")
            return False
        _verify(session)  # confirm the new LCR session works
        logger.info("LCR session renewed via refresh_token + silent SSO")
        return True
    except Exception as exc:  # noqa: BLE001
        logger.info("try_refresh_session failed (non-fatal): %s", exc)
        return False


def login(
    identifier: str | None = None,
    password: str | None = None,
    storage_state_path: str | Path = DEFAULT_STORAGE_STATE,
    verify: bool = True,
) -> Path:
    """Log in to LCR with zero browser and write storage_state.json. Returns its path."""
    from dotenv import load_dotenv

    load_dotenv()
    identifier = identifier or os.getenv("LCR_LOGIN")
    password = password or os.getenv("LCR_PASSWORD")
    if not identifier or not password:
        raise LoginError("LCR_LOGIN / LCR_PASSWORD not set (env or args).")

    path = Path(storage_state_path)
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    _authenticate_okta(session, identifier, password)
    _establish_lcr_session(session)
    n = _write_storage_state(session, path)
    logger.info("wrote %d cookies -> %s", n, path)

    if verify:
        me = _verify(session)
        who = me.get("name") or me.get("preferredName") or me.get("email") or "?"
        logger.info("verified LCR session for: %s", who)
    return path


def main() -> int:
    try:
        path = login()
    except LoginError as exc:
        logger.error("login failed: %s", exc)
        print(f"[!] {exc}")
        return 1
    print(f"[+] storage_state written -> {path}")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
