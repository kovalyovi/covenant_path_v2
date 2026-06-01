"""
MFA-aware Church (Okta IDX) login for the auth-broker.

The browser can't talk to the Church's Okta (CORS), so this runs server-side and
reuses lcr_client.okta_login's IDX helpers. Unlike okta_login.login() (headless, no-MFA,
used by the daily sync — left untouched), this is resumable: start_login may return
`mfa_required`, then select_factor (sends the code) and verify_mfa (submits it) finish.

LOGGING: every IDX step is logged with a short login_id; passwords, MFA codes, tokens and
session cookies are NEVER logged. Failures dump a redacted debug record.

State between steps is held in-memory keyed by login_id (TTL); fine for a single broker.
"""

from __future__ import annotations

import secrets
import time

import requests

from lcr_client.logging_setup import dump_debug, get_logger
from lcr_client.okta_login import (
    CLIENT_ID, INTROSPECT_URL, ISSUER, REDIRECT_URI, SCOPE,
    _follow, _idx_messages, _idx_post, _password_authenticator_id, _pkce,
    _remediations, establish_lcr_session, new_session, verify_session,
)

logger = get_logger()

_PENDING: dict[str, dict] = {}          # login_id -> {session, payload, ts}
_TTL = 600                              # 10 min to complete an MFA challenge


class AuthError(RuntimeError):
    pass


def _new_login_id() -> str:
    return secrets.token_urlsafe(9)


def _prune() -> None:
    cutoff = time.time() - _TTL
    for k in [k for k, v in _PENDING.items() if v["ts"] < cutoff]:
        _PENDING.pop(k, None)


def _factors(remediation: dict) -> list[dict]:
    """Extract selectable 2nd-factor options (id + label + method) from an IDX select."""
    out = []
    for field in remediation.get("value", []):
        if field.get("name") != "authenticator":
            continue
        for opt in field.get("options", []):
            form = opt.get("value", {}).get("form", {}).get("value", [])
            fid = next((f.get("value") for f in form if f.get("name") == "id"), None)
            method = next((f.get("value") for f in form if f.get("name") == "methodType"), None)
            label = opt.get("label", "")
            if fid and "password" not in label.lower():
                out.append({"id": fid, "label": label, "method": method})
    return out


def serialize_cookies(session: requests.Session) -> list[dict]:
    """The LCR session cookies in storage_state shape — what the delegated sync re-mints from.
    Returned only to the broker (server-side, for encrypted storage); never sent to the client."""
    return [{"name": c.name, "value": c.value, "domain": c.domain, "path": c.path or "/"}
            for c in session.cookies]


def _identity(session: requests.Session, login_id: str) -> dict:
    """After IDX success: mint an LCR session and read /api/auth/me for identity."""
    establish_lcr_session(session)
    me = verify_session(session)
    ident = {
        "email": (me.get("email") or me.get("personalEmail") or "").lower(),
        "name": me.get("name") or me.get("displayName"),
        "cmis_id": me.get("churchCMISID") or me.get("churchCMISUUID"),
        "username": me.get("preferred_username"),
    }
    logger.info("[auth %s] success: identified %s", login_id, ident.get("username") or ident.get("email"))
    if not ident["email"]:
        logger.warning("[auth %s] no email on /api/auth/me — RLS-by-email won't match", login_id)
    return ident


def _drive_to_password(session: requests.Session, identifier: str, password: str, login_id: str) -> tuple[dict, str]:
    """interact -> introspect -> identify -> (select password) -> answer password.
    Returns (payload, pkce_verifier) so the caller can exchange the interaction_code for tokens."""
    verifier, challenge = _pkce()
    logger.info("[auth %s] interact", login_id)
    r = session.post(f"{ISSUER}/v1/interact", data={
        "client_id": CLIENT_ID, "scope": SCOPE, "redirect_uri": REDIRECT_URI,
        "code_challenge": challenge, "code_challenge_method": "S256",
        "state": secrets.token_hex(16)},
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        timeout=60)
    if r.status_code >= 400:
        dump_debug("broker_interact_error", login_id=login_id, status=r.status_code)
        raise AuthError(f"interact failed ({r.status_code})")
    logger.info("[auth %s] introspect", login_id)
    payload = _idx_post(session, INTROSPECT_URL, {"interactionHandle": r.json()["interaction_handle"]})

    identified = selected = False
    for _ in range(8):
        if "successWithInteractionCode" in payload:
            return payload, verifier
        rems = _remediations(payload)
        sh = payload.get("stateHandle")
        for rr in rems.values():
            rr["_stateHandle"] = sh
        if not identified and "identify" in rems:
            logger.info("[auth %s] identify", login_id)
            payload = _follow(session, rems["identify"], {"identifier": identifier, "rememberMe": False})
            identified = True
            continue
        if "challenge-authenticator" in rems:
            logger.info("[auth %s] answer password", login_id)
            payload = _follow(session, rems["challenge-authenticator"],
                              {"credentials": {"passcode": password}}, redact=True)
            continue
        if not selected and "select-authenticator-authenticate" in rems:
            aid = _password_authenticator_id(rems["select-authenticator-authenticate"])
            logger.info("[auth %s] select password authenticator", login_id)
            payload = _follow(session, rems["select-authenticator-authenticate"], {"authenticator": {"id": aid}})
            selected = True
            continue
        break  # password done; whatever's next (success or MFA) is handled by the caller
    return payload, verifier


def _exchange_code(session: requests.Session, payload: dict, verifier: str, login_id: str) -> str | None:
    """Exchange the successWithInteractionCode for OAuth tokens; returns refresh_token or None.
    Never raises — a failure just means no refresh_token is captured (login already succeeded)."""
    try:
        code_obj = payload.get("successWithInteractionCode", {})
        values = code_obj.get("value") if isinstance(code_obj.get("value"), list) else []
        interaction_code = next(
            (item.get("value") for item in values
             if isinstance(item, dict) and item.get("name") == "interaction_code"),
            None)
        if not interaction_code:
            logger.warning("[auth %s] no interaction_code in success payload", login_id)
            return None
        token_url = code_obj.get("href", f"{ISSUER}/v1/token")
        resp = session.post(token_url, data={
            "grant_type": "interaction_code",
            "client_id": CLIENT_ID,
            "interaction_code": interaction_code,
            "code_verifier": verifier,
        }, headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
            timeout=30)
        if resp.status_code != 200:
            logger.warning("[auth %s] token exchange failed (%s)", login_id, resp.status_code)
            return None
        rt = resp.json().get("refresh_token")
        if rt:
            logger.info("[auth %s] refresh_token captured for long-lived renewal", login_id)
        return rt
    except Exception as exc:  # noqa: BLE001
        logger.warning("[auth %s] token exchange error (non-fatal): %s", login_id, exc)
        return None


def start_login(username: str, password: str) -> dict:
    """Begin a Church login. Returns {status: 'success', identity} or
    {status: 'mfa_required', login_id, factors:[{id,label,method}]}."""
    _prune()
    login_id = _new_login_id()
    session = new_session()
    try:
        payload, verifier = _drive_to_password(session, username, password, login_id)
    except AuthError:
        raise
    except Exception as exc:  # noqa: BLE001
        dump_debug("broker_login_error", login_id=login_id, error=str(exc))
        raise AuthError(f"login failed: {exc}") from exc

    if "successWithInteractionCode" in payload:
        rt = _exchange_code(session, payload, verifier, login_id)
        ident = _identity(session, login_id)
        if rt:
            ident["refresh_token"] = rt
        return {"status": "success", "identity": ident, "cookies": serialize_cookies(session)}

    rems = _remediations(payload)
    if "select-authenticator-authenticate" in rems:
        factors = _factors(rems["select-authenticator-authenticate"])
        if factors:
            _PENDING[login_id] = {"session": session, "payload": payload,
                                  "verifier": verifier, "ts": time.time()}
            logger.info("[auth %s] MFA required; factors=%s", login_id, [f["label"] for f in factors])
            return {"status": "mfa_required", "login_id": login_id, "factors": factors}
    # unexpected (e.g. wrong password surfaces as messages)
    msg = _idx_messages(payload)
    dump_debug("broker_login_stuck", login_id=login_id, remediations=sorted(rems), messages=msg)
    raise AuthError(msg or "login could not complete (check username/password)")


def select_factor(login_id: str, factor_id: str) -> dict:
    """Choose an MFA factor — sends the code (email/SMS) or readies the prompt."""
    pend = _PENDING.get(login_id)
    if not pend:
        raise AuthError("login session expired — start over")
    session, payload = pend["session"], pend["payload"]
    rems = _remediations(payload)
    sel = rems.get("select-authenticator-authenticate")
    if not sel:
        raise AuthError("no factor selection available")
    sel["_stateHandle"] = payload.get("stateHandle")
    logger.info("[auth %s] select MFA factor", login_id)
    pend["payload"] = _follow(session, sel, {"authenticator": {"id": factor_id}})
    pend["ts"] = time.time()
    return {"status": "code_sent"}


def verify_mfa(login_id: str, code: str) -> dict:
    """Submit the MFA code and finish login."""
    pend = _PENDING.get(login_id)
    if not pend:
        raise AuthError("login session expired — start over")
    session, payload = pend["session"], pend["payload"]
    verifier = pend.get("verifier", "")
    rems = _remediations(payload)
    ch = rems.get("challenge-authenticator")
    if not ch:
        raise AuthError("no MFA challenge pending — select a factor first")
    ch["_stateHandle"] = payload.get("stateHandle")
    logger.info("[auth %s] verify MFA code", login_id)
    try:
        payload = _follow(session, ch, {"credentials": {"passcode": code}}, redact=True)
    except Exception as exc:  # noqa: BLE001
        dump_debug("broker_mfa_error", login_id=login_id, error=str(exc))
        raise AuthError(f"MFA verification failed: {exc}") from exc
    if "successWithInteractionCode" not in payload:
        raise AuthError(_idx_messages(payload) or "incorrect code")
    rt = _exchange_code(session, payload, verifier, login_id)
    ident = _identity(session, login_id)
    if rt:
        ident["refresh_token"] = rt
    cookies = serialize_cookies(session)
    _PENDING.pop(login_id, None)
    return {"status": "success", "identity": ident, "cookies": cookies}


def verify_captured_session(cookies: list[dict]) -> dict:
    """Native WebView path: the app captured the Okta/LCR session itself (password only
    to Okta). Verify it server-side and return identity — no password ever reaches us."""
    from lcr_client.okta_login import session_from_cookies
    session = session_from_cookies(cookies)
    login_id = _new_login_id()
    try:
        return {"status": "success", "identity": _identity(session, login_id),
                "cookies": serialize_cookies(session)}
    except Exception as exc:  # noqa: BLE001
        dump_debug("broker_session_verify_error", login_id=login_id, error=str(exc))
        raise AuthError(f"could not verify captured session: {exc}") from exc
