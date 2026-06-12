"""
Credential-capture login — the ONE-MFA flow that yields everything a stake's daily sync needs.

The broker's ordinary login (okta_flow.py) drives the IDX interaction-code grant. That verifies the
password + MFA and gets us the user's identity, but the resulting Okta session CANNOT silently mint
a Member Tools token (Okta re-applies MFA to the Member Tools app — proven 2026-06-12), so a
delegated stake could never get the 45-day token that lets the daily sync run unattended.

This module drives the flow the official apps use (reverse-engineered from rickybloomfield/
Mission-KPIs, verified live 2026-06-12):

    POST /api/v1/authn (username+password)         -> sessionToken           (no MFA at this step)
    GET  lcr /api/auth/login -> the LCR OAuth /authorize URL
    GET  /authorize?...&sessionToken=...           -> the Okta IDX widget (MFA) OR direct success
    [MFA] introspect the stateToken -> select-authenticator -> challenge-authenticator (the ONE code)
    follow success.href -> lcr /api/auth/callback  -> appSession set (LCR session)
    membertools.mint_from_okta_session(session)    -> 45-day refresh token   (silent — same session)

So a SINGLE MFA completion establishes the LCR session AND a mintable Okta session, and we mint the
Member Tools 45-day token off it. No stored password, no stored TOTP — just the (already-encrypted)
45-day token rides the credential, and the daily sync renews off it for 45 days.

Resumable like okta_flow: web_start -> (web_select_factor) -> web_verify, keyed by a login_id in
_WEB_PENDING. Reuses okta_flow's factor parsing / friendly MFA-failure classification / identity tail
so the user-facing behavior (factor picker, code entry, errors) matches the password lane exactly.
"""

from __future__ import annotations

import re
import secrets
import time
from urllib.parse import parse_qs, urlparse

import requests

from lcr_client.logging_setup import get_logger
from lcr_client.okta_login import (
    IDENTITY_BASE, INTROSPECT_URL, LCR, _follow, _idx_post, _pkce, _remediations, new_session,
)
from backend.auth_broker import okta_flow
from backend.auth_broker.okta_flow import (
    AuthError, IdentityError, _authenticator_types, _challenge_code_field, _classify_mfa_failure,
    _factors, _idx_messages, _idx_summary, _identity, _new_login_id, _public_factors,
    _split_supported, serialize_cookies,
)

logger = get_logger()

# The Member Tools UA — Akamai fingerprints the client; mirror it so id/lcr see a familiar one.
_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
_IDX_HEADERS = {"Accept": "application/ion+json; okta-version=1.0.0",
                "Content-Type": "application/ion+json; okta-version=1.0.0"}

# login_id -> {session, payload, factors, username, ts}. Separate from okta_flow._PENDING so the two
# flows never collide; same TTL pruning contract.
_WEB_PENDING: dict[str, dict] = {}
_TTL_S = 600.0


def _prune() -> None:
    cut = time.time() - _TTL_S
    for k in [k for k, v in _WEB_PENDING.items() if v.get("ts", 0) < cut]:
        _WEB_PENDING.pop(k, None)


# --- the auth legs -------------------------------------------------------------------------------

def _authn(session: requests.Session, username: str, password: str, login_id: str) -> str:
    """Classic /api/v1/authn -> sessionToken. The Church org returns SUCCESS here without MFA (MFA is
    applied at the OAuth /authorize step); a bad password is a clean 401 we surface friendly."""
    r = session.post(f"{IDENTITY_BASE}/api/v1/authn",
                     json={"username": username, "password": password},
                     headers={"User-Agent": _UA, "Accept": "application/json",
                              "Content-Type": "application/json"}, timeout=60)
    if r.status_code == 401:
        raise AuthError("That username or password is incorrect. It's the same Church Account you "
                        "use for LCR / churchofjesuschrist.org — please check both and try again.",
                        kind="bad_credentials", root_cause=f"authn 401", username=username)
    if r.status_code >= 400:
        raise AuthError("The Church sign-in service didn't respond — please try again in a moment.",
                        kind="authn_error", root_cause=f"authn {r.status_code}", username=username)
    j = r.json()
    token = j.get("sessionToken")
    if not token:
        # MFA_REQUIRED here would be an org with authn-level MFA (not the Church's current policy).
        raise AuthError("Your Church Account needs an extra verification step we can't complete "
                        "automatically. Please sign in once at lcr.churchofjesuschrist.org, then retry.",
                        kind="authn_no_token", root_cause=f"authn status={j.get('status')}",
                        username=username)
    return token


def _open_lcr_authorize(session: requests.Session, session_token: str, login_id: str) -> dict | None:
    """Drive lcr /api/auth/login -> the LCR OAuth /authorize (with the sessionToken). Returns the IDX
    payload when Okta presents the MFA widget, or None when it completed silently (no MFA — appSession
    is already set). Raises if the authorize didn't reach either."""
    loc = session.get(f"{LCR}/api/auth/login", params={"returnTo": "/"},
                      allow_redirects=False, timeout=60,
                      headers={"User-Agent": _UA, "Accept": "text/html,*/*"}).headers.get("Location")
    if not loc:
        raise AuthError("The Church sign-in service didn't start the session — please try again.",
                        kind="authorize_no_redirect", root_cause="lcr /api/auth/login no Location")
    authz = loc + ("&" if "?" in loc else "?") + "sessionToken=" + session_token
    body = session.get(authz, allow_redirects=True, timeout=60,
                       headers={"User-Agent": _UA, "Accept": "text/html,*/*"}).text
    m = re.search(r'"stateToken":"([^"]+)"', body) or re.search(r'stateToken=([\w.\-~\\]+)', body)
    if not m:
        # No widget → either it completed (appSession set) or it's an unexpected page.
        if any(c.name.startswith("appSession") for c in session.cookies):
            logger.info("[web %s] authorize completed without MFA (appSession set)", login_id)
            return None
        raise AuthError("Your Church sign-in didn't complete — please try again.",
                        kind="authorize_stuck", root_cause="authorize returned no widget, no appSession")
    state_token = m.group(1).encode().decode("unicode_escape")
    payload = _idx_post(session, INTROSPECT_URL, {"stateToken": state_token})
    logger.info("[web %s] MFA widget -> %s", login_id, _idx_summary(payload))
    return payload


def _follow_success(session: requests.Session, payload: dict, login_id: str) -> None:
    """Follow the IDX success href so Okta completes the LCR OAuth redirect chain and sets appSession.
    (Already-set appSession is a no-op.)"""
    success = payload.get("successWithInteractionCode") or payload.get("success")
    if success and success.get("href"):
        session.get(success["href"], allow_redirects=True, timeout=60,
                    headers={"User-Agent": _UA, "Accept": "text/html,*/*"})
    if not any(c.name.startswith("appSession") for c in session.cookies):
        raise IdentityError("Your Church sign-in worked, but the LCR session wasn't established — "
                            "please try again in a minute.", kind="sso_rejected",
                            root_cause="no appSession after success")


def _mint_membertools(session: requests.Session, login_id: str) -> str | None:
    """Silently mint the Member Tools 45-day token off the now-MFA-satisfied session. Best-effort:
    a mint failure (e.g. the member has never used Member Tools) must not fail the login — the daily
    sync just won't have the bulk token until the next re-auth."""
    try:
        from lcr_client import membertools
        tok = membertools.mint_from_okta_session(session)
        rt = tok.get("refresh_token")
        if rt:
            logger.info("[web %s] Member Tools 45-day token minted", login_id)
        else:
            logger.warning("[web %s] Member Tools mint returned no refresh token", login_id)
        return rt
    except Exception as exc:  # noqa: BLE001
        logger.warning("[web %s] Member Tools mint skipped: %s", login_id, exc)
        return None


# --- the resumable API (mirrors okta_flow.start_login / select_factor / verify_mfa) --------------

def web_start(username: str, password: str) -> dict:
    """Begin a credential-capture login. Returns {status:'success', identity, cookies,
    membertools_refresh} when there's no MFA, or {status:'mfa_required', login_id, factors,...}."""
    _prune()
    login_id = _new_login_id()
    session = new_session()
    session.headers.update({"User-Agent": _UA})
    token = _authn(session, username, password, login_id)
    payload = _open_lcr_authorize(session, token, login_id)
    if payload is None:  # no MFA — session is live; finish now
        return _finish(session, payload={}, login_id=login_id, username=username)

    rems = _remediations(payload)
    types = _authenticator_types(payload)
    sel = rems.get("select-authenticator-authenticate")
    if sel and _factors(sel, types):
        factors, dropped = _split_supported(_factors(sel, types))
        if not factors:
            raise AuthError(okta_flow._NO_SUPPORTED_FACTORS_MSG, kind="mfa_unsupported",
                            root_cause=f"only unsupported MFA factors: {dropped}", username=username)
        offered = [f["type"] or f["method"] or "?" for f in factors]
        logger.info("[web %s] MFA required; factors=%s dropped=%s", login_id, offered, dropped)
        _WEB_PENDING[login_id] = {"session": session, "payload": payload, "factors": factors,
                                  "username": username, "ts": time.time()}
        return {"status": "mfa_required", "login_id": login_id, "factors": _public_factors(factors),
                "factor_types": offered, "dropped_factor_types": dropped}
    if "challenge-authenticator" in rems and _challenge_code_field(rems["challenge-authenticator"]):
        _WEB_PENDING[login_id] = {"session": session, "payload": payload, "factors": [],
                                  "username": username, "ts": time.time()}
        return {"status": "mfa_required", "login_id": login_id,
                "factors": [{"id": "pending", "label": "your verification method", "method": "otp"}],
                "factor_types": sorted(set(types.values()))}
    raise AuthError("We couldn't complete the sign-in — please try again.", kind="web_stuck",
                    root_cause=f"unexpected remediations: {sorted(rems)}", username=username)


def web_select_factor(login_id: str, factor_id: str) -> dict:
    """Choose an MFA factor — sends the email/SMS code, or readies the authenticator prompt."""
    pend = _WEB_PENDING.get(login_id)
    if not pend:
        raise AuthError(okta_flow._EXPIRED_MSG, kind="mfa_expired")
    session, payload = pend["session"], pend["payload"]
    sel = _remediations(payload).get("select-authenticator-authenticate")
    if not sel:
        if "challenge-authenticator" in _remediations(payload):
            return {"status": "code_sent"}
        raise AuthError("We couldn't send a verification code — please start signing in again.",
                        kind="mfa_no_selection", username=pend.get("username"))
    sel["_stateHandle"] = payload.get("stateHandle")
    factor = next((f for f in pend["factors"] if f["id"] == factor_id), None)
    auth_obj = (factor or {}).get("_auth") or {"id": factor_id}
    ftype = (factor or {}).get("type") or "?"
    logger.info("[web %s] select MFA factor type=%s", login_id, ftype)
    try:
        new_payload = _follow(session, sel, {"authenticator": auth_obj})
    except Exception as exc:  # noqa: BLE001
        raise AuthError(_idx_messages(getattr(exc, "payload", {}) or {}) or "We couldn't start that "
                        "verification method — please try a different one.", kind="mfa_select_failed",
                        root_cause=str(exc), username=pend.get("username"), factor_type=ftype) from exc
    if "challenge-authenticator" not in _remediations(new_payload):
        raise AuthError(_idx_messages(new_payload) or "We couldn't start that verification method — "
                        "please try a different one.", kind="mfa_select_failed",
                        username=pend.get("username"), factor_type=ftype)
    pend["payload"] = new_payload
    pend["selected_type"] = ftype
    pend["ts"] = time.time()
    return {"status": "code_sent"}


def web_verify(login_id: str, code: str) -> dict:
    """Answer the MFA code, complete the LCR OAuth (appSession), and mint the Member Tools token.
    Returns {status:'success', identity, cookies, membertools_refresh}."""
    pend = _WEB_PENDING.get(login_id)
    if not pend:
        raise AuthError(okta_flow._EXPIRED_MSG, kind="mfa_expired")
    session, payload = pend["session"], pend["payload"]
    username = pend.get("username") or ""
    ftype = pend.get("selected_type") or "?"
    ch = _remediations(payload).get("challenge-authenticator")
    if not ch:
        raise AuthError(okta_flow._EXPIRED_MSG, kind="mfa_no_challenge", username=username)
    field = _challenge_code_field(ch) or "passcode"
    ch["_stateHandle"] = payload.get("stateHandle")
    norm = code.replace(" ", "").replace("-", "")
    try:
        new_payload = _follow(session, ch, {"credentials": {field: norm}})
    except Exception as exc:  # noqa: BLE001
        err = getattr(exc, "payload", None) or {}
        if err.get("stateHandle"):
            pend["payload"] = err
            pend["ts"] = time.time()
        raise _classify_mfa_failure(str(exc), _idx_messages(err), username=username,
                                    factor_type=ftype) from exc
    if not (new_payload.get("successWithInteractionCode") or new_payload.get("success")):
        pend["payload"] = new_payload
        pend["ts"] = time.time()
        raise _classify_mfa_failure("MFA answer accepted but login did not complete",
                                    _idx_messages(new_payload), username=username, factor_type=ftype)
    return _finish(session, new_payload, login_id, username)


def _finish(session: requests.Session, payload: dict, login_id: str, username: str) -> dict:
    """Shared tail: follow success -> appSession, read identity, mint Member Tools, clean up."""
    _follow_success(session, payload, login_id)
    ident = _identity(session, login_id)
    membertools_refresh = _mint_membertools(session, login_id)
    _WEB_PENDING.pop(login_id, None)
    return {"status": "success", "identity": ident, "cookies": serialize_cookies(session),
            "membertools_refresh": membertools_refresh}
