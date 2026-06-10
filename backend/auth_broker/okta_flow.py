"""
MFA-aware Church (Okta IDX) login for the auth-broker.

The browser can't talk to the Church's Okta (CORS), so this runs server-side and
reuses lcr_client.okta_login's IDX helpers. Unlike okta_login.login() (headless, no-MFA,
used by the daily sync — left untouched), this is resumable: start_login may return
`mfa_required`, then select_factor (sends the code) and verify_mfa (submits it) finish.

LOGGING: every IDX step is logged with a short login_id; passwords, MFA codes, tokens and
session cookies are NEVER logged. We DO log (PII-safe) the remediation names, the factor TYPES
offered/selected, and the response SHAPE (top-level keys + status) at each IDX step, so the next
failure is fully diagnosable from logs alone. Failures dump a redacted debug record.

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
from backend.auth_broker import identity_cache

logger = get_logger()

_PENDING: dict[str, dict] = {}          # login_id -> {session, payload, ts}
_TTL = 600                              # 10 min to complete an MFA challenge


class AuthError(RuntimeError):
    pass


class IdentityError(AuthError):
    """Okta ACCEPTED the password, but the LCR identity fetch failed — we can't learn the email to
    mint a session for. Not a credential problem: the API layer maps this to 503 with an honest
    "LCR didn't answer, try again" message (previously it escaped as an opaque 500 after a hang)."""


def _new_login_id() -> str:
    return secrets.token_urlsafe(9)


def _prune() -> None:
    cutoff = time.time() - _TTL
    for k in [k for k, v in _PENDING.items() if v["ts"] < cutoff]:
        _PENDING.pop(k, None)


def _authenticator_types(payload: dict) -> dict[str, str]:
    """Map authenticator id -> Okta `key` (e.g. okta_email, google_otp, phone_number, okta_verify,
    webauthn) from the IDX `authenticators.value[]`. The key is a stable factor TYPE — far more useful
    for logging/branching than the human label (which is localized and account-specific). PII-safe:
    keys are factor types, never phone numbers or emails."""
    out: dict[str, str] = {}
    for auth in payload.get("authenticators", {}).get("value", []):
        aid, key = auth.get("id"), auth.get("key")
        if aid and key:
            out[aid] = key
    return out


def _authenticator_object(opt: dict) -> dict:
    """Build the FULL `authenticator` body Okta expects for a select-authenticator option, from the
    option's nested form. Mirrors Mission-KPIs' `option_authenticator_object` / `extractFactors`:
    we must send EVERY form field (id, methodType, enrollmentId, …) — not just `id`. A phone factor
    in particular needs `enrollmentId` (and methodType sms/voice) alongside `id`, or Okta accepts the
    /challenge POST but never actually sends the SMS (the silent failure that strands a stake member
    on the code screen with no code arriving). Nested choices (phone: sms vs voice) default to the
    first option. Values are opaque ids/method-types — never the phone number or email itself."""
    form = opt.get("value", {}).get("form", {}).get("value", [])
    obj: dict = {}
    for f in form:
        name = f.get("name")
        if not name:
            continue
        if "value" in f:
            obj[name] = f["value"]
        elif f.get("options"):
            nested = f["options"][0] if f["options"] else None
            if isinstance(nested, dict) and "value" in nested:
                obj[name] = nested["value"]
    return obj


def _factors(remediation: dict, types: dict[str, str] | None = None) -> list[dict]:
    """Extract selectable 2nd-factor options from an IDX select. Each entry carries:
      - id/label/method: the client-facing summary (the unchanged shape the apps already render),
      - type: the Okta factor key (okta_email/google_otp/phone_number/…) for logging,
      - _auth: the FULL authenticator body to POST on select (see `_authenticator_object`).
    The password option is dropped (it's the primary factor, not a 2nd factor)."""
    types = types or {}
    out = []
    for field in remediation.get("value", []):
        if field.get("name") != "authenticator":
            continue
        for opt in field.get("options", []):
            auth = _authenticator_object(opt)
            fid = auth.get("id")
            method = auth.get("methodType")
            label = opt.get("label", "")
            ftype = types.get(fid, "")
            # Drop the password authenticator — by type when known, else by label fallback.
            is_password = ftype == "okta_password" or (not ftype and "password" in label.lower())
            if fid and not is_password:
                out.append({"id": fid, "label": label, "method": method,
                            "type": ftype, "_auth": auth})
    return out


def _public_factors(factors: list[dict]) -> list[dict]:
    """Strip the internal `_auth`/`type` before returning factors to the client (unchanged wire shape)."""
    return [{"id": f["id"], "label": f["label"], "method": f["method"]} for f in factors]


def _idx_summary(payload: dict) -> dict:
    """A PII-SAFE one-glance summary of an IDX response for logging: which remediations are offered,
    the top-level keys present, whether it's a terminal success, the factor TYPES on offer, and
    whether Okta attached human messages. NEVER includes codes, passwords, tokens, phone numbers,
    emails, names, or the raw payload — only structural shape + factor types."""
    rems = sorted(_remediations(payload))
    types = sorted(set(_authenticator_types(payload).values()))
    return {
        "remediations": rems,
        "top_keys": sorted(k for k in payload if k not in ("remediation", "authenticators")),
        "success": "successWithInteractionCode" in payload or "success" in payload,
        "factor_types": types,
        "has_messages": bool(payload.get("messages", {}).get("value")),
    }


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
    logger.info("[auth %s] introspect -> %s", login_id, _idx_summary(payload))

    identified = selected = answered_password = False
    for _ in range(8):
        if "successWithInteractionCode" in payload:
            return payload, verifier
        rems = _remediations(payload)
        sh = payload.get("stateHandle")
        for rr in rems.values():
            rr["_stateHandle"] = sh
        if not identified and "identify" in rems:
            logger.info("[auth %s] identify", login_id)
            # rememberMe=True: the OAuth refresh_token exchange is rejected by the Church's Okta
            # (invalid_client — verified 2026-06-09; this client only issues tokens via the web SSO
            # flow our headless replay can't complete), so a credential CANNOT self-renew. The one
            # lever we have on cadence is the session's own lifetime — a persistent ("remember me")
            # Okta session makes the stored cookies + tier-2 re-SSO last weeks instead of hours, so
            # manual re-auth is needed far less often.
            payload = _follow(session, rems["identify"], {"identifier": identifier, "rememberMe": True})
            identified = True
            continue
        # Answer the PASSWORD challenge exactly ONCE. A second `challenge-authenticator` after this is
        # an MFA factor (e.g. an emailed/authenticator code) — we must NOT resubmit the password into
        # it (that fails the login). Stop here and let the resumable MFA steps (select/verify) finish.
        if not answered_password and "challenge-authenticator" in rems:
            logger.info("[auth %s] answer password", login_id)
            payload = _follow(session, rems["challenge-authenticator"],
                              {"credentials": {"passcode": password}}, redact=True)
            answered_password = True
            logger.info("[auth %s] post-password -> %s", login_id, _idx_summary(payload))
            continue
        if not selected and "select-authenticator-authenticate" in rems:
            aid = _password_authenticator_id(rems["select-authenticator-authenticate"])
            logger.info("[auth %s] select password authenticator", login_id)
            payload = _follow(session, rems["select-authenticator-authenticate"], {"authenticator": {"id": aid}})
            selected = True
            continue
        logger.info("[auth %s] password phase done -> %s", login_id, _idx_summary(payload))
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


def _store_pending(login_id: str, session: requests.Session, payload: dict,
                   verifier: str, factors: list[dict], username: str = "") -> None:
    _PENDING[login_id] = {"session": session, "payload": payload, "verifier": verifier,
                          "factors": factors, "username": username, "ts": time.time()}


def _finish_success(session: requests.Session, payload: dict, verifier: str, login_id: str,
                    cid: str, t0: float, username: str,
                    want_refresh_token: bool, allow_cached_identity: bool) -> dict:
    """Shared tail of a successful password/MFA verification: resolve the identity and time it.

    CACHE FAST LANE (plain repeat sign-ins): Okta just verified the password, and church_identities
    already maps this username to a verified email/name/unit from a prior full login — so the LCR
    SSO + /api/auth/me leg (measured 13s on a good day, 90s+ with LCR under load; the dominant cost
    of a warm sign-in) is pure re-derivation and is SKIPPED. Cookies stay Okta-only; the login eval
    establishes an LCR session itself in the one case it still needs one (no usable stake credential).

    FULL PATH (first login on this broker DB, cache miss, or enroll): the interaction-code exchange
    runs only when the refresh token is actually wanted (enroll stores it; it currently 401s anyway),
    then the LCR identity fetch — now guarded: an LCR failure surfaces as IdentityError instead of
    an unhandled 500 after a ~90s hang. A successful full fetch (re)fills the cache."""
    from backend import observability as obs
    cached = identity_cache.get(username) if allow_cached_identity else None
    if cached and cached.get("email"):
        ident = {"email": cached["email"], "name": cached.get("name"),
                 "cmis_id": cached.get("cmis_id"), "username": cached.get("username"),
                 "login_username": username, "unit_number": cached.get("unit_number"),
                 "stake_name": cached.get("stake_name"), "cached": True}
        ms = round((time.time() - t0) * 1000, 1)
        obs.event("login.complete", correlation_id=cid, status="success", duration_ms=ms,
                  lane="cached")
        logger.info("[auth %s] login.complete in %.0fms (cached identity — no LCR)", login_id, ms)
        return ident
    rt = None
    if want_refresh_token:
        with obs.span("login.token_exchange", correlation_id=cid):
            rt = _exchange_code(session, payload, verifier, login_id)
    try:
        with obs.span("login.identity", correlation_id=cid, endpoint="lcr"):
            ident = _identity(session, login_id)
    except Exception as exc:  # noqa: BLE001 — LCR failed AFTER the password was accepted
        dump_debug("broker_identity_error", login_id=login_id, error=str(exc))
        obs.event("login.complete", correlation_id=cid, status="error",
                  duration_ms=round((time.time() - t0) * 1000, 1), message=str(exc)[:200])
        raise IdentityError(
            "Your password was accepted, but the Church directory (LCR) didn't answer when we "
            "asked who you are — it may be slow or briefly down. Please try again in a minute."
        ) from exc
    ident["login_username"] = username
    if rt:
        ident["refresh_token"] = rt
    identity_cache.put(username, ident)
    ms = round((time.time() - t0) * 1000, 1)
    obs.event("login.complete", correlation_id=cid, status="success", duration_ms=ms, lane="full")
    logger.info("[auth %s] login.complete in %.0fms (full identity)", login_id, ms)
    return ident


def start_login(username: str, password: str, *, want_refresh_token: bool = True,
                allow_cached_identity: bool = False) -> dict:
    """Begin a Church login. Returns {status: 'success', identity} or
    {status: 'mfa_required', login_id, factors:[{id,label,method}]}.

    allow_cached_identity: plain sign-ins serve identity from church_identities once Okta verifies
    the password (skipping the slow LCR leg — see _finish_success). want_refresh_token: only an
    enroll needs the interaction-code exchange (the token rides the stored credential)."""
    from backend import observability as obs
    _prune()
    login_id = _new_login_id()
    cid = obs.new_correlation_id()  # ties this login's phases together in Axiom (#6 login profiling)
    session = new_session()
    _t0 = time.time()
    try:
        with obs.span("login.password", correlation_id=cid, endpoint="okta"):
            payload, verifier = _drive_to_password(session, username, password, login_id)
    except AuthError:
        raise
    except Exception as exc:  # noqa: BLE001
        dump_debug("broker_login_error", login_id=login_id, error=str(exc))
        raise AuthError(f"login failed: {exc}") from exc

    if "successWithInteractionCode" in payload:
        ident = _finish_success(session, payload, verifier, login_id, cid, _t0, username,
                                want_refresh_token, allow_cached_identity)
        return {"status": "success", "identity": ident, "cookies": serialize_cookies(session)}

    rems = _remediations(payload)
    types = _authenticator_types(payload)
    # MFA shape A: Okta offers a list of 2nd-factor authenticators to choose from.
    if "select-authenticator-authenticate" in rems and _factors(rems["select-authenticator-authenticate"], types):
        factors = _factors(rems["select-authenticator-authenticate"], types)
        _store_pending(login_id, session, payload, verifier, factors, username)
        # Log the factor TYPES offered (PII-safe) — so if a member's only factor is one we mishandle
        # (e.g. webauthn/security key), the logs show exactly what was on the menu.
        logger.info("[auth %s] MFA required (shape A); factor_types=%s", login_id,
                    [f["type"] or f["method"] or "?" for f in factors])
        return {"status": "mfa_required", "login_id": login_id, "factors": _public_factors(factors)}
    # MFA shape B: single-factor — Okta went straight to the code challenge (often after auto-sending
    # an email/SMS code). Surface a generic factor so the app shows the code field; select_factor is a
    # no-op (the code is already pending) and verify_mfa submits it. (Previously this raised "stuck".)
    if "challenge-authenticator" in rems:
        _store_pending(login_id, session, payload, verifier, [], username)
        logger.info("[auth %s] MFA required (shape B); single-factor code challenge, types=%s",
                    login_id, sorted(set(types.values())))
        return {"status": "mfa_required", "login_id": login_id,
                "factors": [{"id": "pending", "label": "your verification method", "method": "otp"}]}
    # Unexpected — log the full PII-safe shape so the next stuck login is diagnosable. Common causes:
    # the account's only factor needs enrollment (`enroll-authenticator` / `select-authenticator-enroll`),
    # or a remediation we don't drive yet. The IDX `messages` (if any) usually name the real reason.
    summary = _idx_summary(payload)
    msg = _idx_messages(payload)
    logger.warning("[auth %s] login stuck after password -> %s", login_id, summary)
    dump_debug("broker_login_stuck", login_id=login_id, summary=summary, messages=msg)
    raise AuthError(msg or "login could not complete (check username/password)")


def select_factor(login_id: str, factor_id: str) -> dict:
    """Choose an MFA factor — sends the code (email/SMS/voice) or readies the prompt (TOTP)."""
    pend = _PENDING.get(login_id)
    if not pend:
        raise AuthError("login session expired — start over")
    session, payload = pend["session"], pend["payload"]
    rems = _remediations(payload)
    sel = rems.get("select-authenticator-authenticate")
    if not sel:
        # Single-factor MFA already at the code challenge (code sent at password time) — nothing to
        # select, so the app's auto-send step is a no-op and we go straight to entering the code.
        if "challenge-authenticator" in rems:
            return {"status": "code_sent"}
        raise AuthError("no factor selection available")
    sel["_stateHandle"] = payload.get("stateHandle")
    # Send the FULL authenticator object (id + methodType + enrollmentId + nested choices) captured at
    # start_login, NOT just {id}. For phone (SMS/voice) factors the `enrollmentId`/`methodType` are
    # required or Okta silently never sends the code — the exact failure that strands a member on the
    # code screen. Fall back to {id} only if we somehow don't have the stored form (older pending).
    factor = next((f for f in pend.get("factors", []) if f["id"] == factor_id), None)
    auth_obj = (factor or {}).get("_auth") or {"id": factor_id}
    ftype = (factor or {}).get("type") or "?"
    logger.info("[auth %s] select MFA factor type=%s fields=%s", login_id, ftype, sorted(auth_obj))
    new_payload = _follow(session, sel, {"authenticator": auth_obj})
    logger.info("[auth %s] post-select -> %s", login_id, _idx_summary(new_payload))
    # If Okta returned no challenge and no success, the select didn't take (e.g. an unsupported factor,
    # or a phone send that needed a field we lacked). Surface the IDX message so it's not a blank wall.
    new_rems = _remediations(new_payload)
    if "challenge-authenticator" not in new_rems and not (
            "successWithInteractionCode" in new_payload or "success" in new_payload):
        msg = _idx_messages(new_payload)
        logger.warning("[auth %s] select_factor produced no challenge (type=%s) -> %s",
                       login_id, ftype, _idx_summary(new_payload))
        dump_debug("broker_select_no_challenge", login_id=login_id, factor_type=ftype,
                   summary=_idx_summary(new_payload), messages=msg)
        raise AuthError(msg or f"couldn't start the {ftype} verification — try a different method")
    pend["payload"] = new_payload
    pend["ts"] = time.time()
    return {"status": "code_sent"}


def verify_mfa(login_id: str, code: str, *, want_refresh_token: bool = True,
               allow_cached_identity: bool = False) -> dict:
    """Submit the MFA code and finish login (same fast-lane/full-path tail as start_login)."""
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
    logger.info("[auth %s] post-verify -> %s", login_id, _idx_summary(payload))
    if "successWithInteractionCode" not in payload:
        # Keep the (refreshed) state so a wrong-code retry uses the latest stateHandle, not a stale one.
        pend["payload"] = payload
        pend["ts"] = time.time()
        raise AuthError(_idx_messages(payload) or "incorrect code")
    from backend import observability as obs
    cid = obs.new_correlation_id()
    # t0 = now: times only this completion leg (the gap since start_login is human typing time).
    ident = _finish_success(session, payload, verifier, login_id, cid, time.time(),
                            pend.get("username") or "", want_refresh_token, allow_cached_identity)
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

# (The background cache refresh lives in enroll.refresh_cached_identity — it also re-reads the
# UNIT via user_context, which a /api/auth/me-only refresher here couldn't.)
