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

import os
import re
import secrets
import time

import requests

from lcr_client.logging_setup import dump_debug, get_logger
from lcr_client.okta_login import (
    CLIENT_ID, INTROSPECT_URL, ISSUER, REDIRECT_URI, SCOPE,
    _follow, _idx_messages, _idx_post, _password_authenticator_id, _pkce,
    _remediations, classify_lcr_failure, establish_and_verify, new_session,
)
from backend.auth_broker import identity_cache

logger = get_logger()

_PENDING: dict[str, dict] = {}          # login_id -> {session, payload, ts, fails}
_TTL = 600                              # 10 min to complete an MFA challenge
# BACKEND-01: lock a pending login after N wrong codes so a captured login_id can't be used to
# brute-force the 6-digit code (a failed verify otherwise keeps the pending alive indefinitely).
# Generous so a legitimate fat-finger retry is never affected; env-tunable.
_MFA_MAX_FAILS = int(os.environ.get("MFA_MAX_FAILS", "6"))


class AuthError(RuntimeError):
    """Login failed at the Okta stage. The MESSAGE is what the user sees (broker `detail`, rendered
    verbatim by all three surfaces); `kind`/`root_cause` keep the raw failure for login_audit — a
    member saw "IDX step answer failed: Authentication failed" instead of "wrong password" because
    the raw text doubled as the user message."""

    def __init__(self, message: str, *, kind: str = "other", root_cause: str = "",
                 username: str = "", factor_type: str = ""):
        super().__init__(message)
        self.kind = kind
        self.root_cause = root_cause or message
        # Attribution for login_audit: MFA-stage endpoints only know a login_id, so the audit rows
        # had who="" — a member stuck at MFA was unattributable (the Ricky Bloomfield dig needed
        # timestamp archaeology). The flow attaches what it knows from the pending state.
        self.username = username
        self.factor_type = factor_type


class IdentityError(AuthError):
    """Okta ACCEPTED the password, but the LCR identity fetch failed — we can't learn the email to
    mint a session for. Not a credential problem: the API layer maps this to 503 with an honest
    "LCR didn't answer, try again" message (previously it escaped as an opaque 500 after a hang).
    Carries `kind` (classify_lcr_failure) + `root_cause` so login_audit records the actual failure
    (e.g. 'auth/me 502'), not just the friendly text — the 2026-06-10 outage was undiagnosable
    from audit rows alone."""


def friendly_auth_error(exc: Exception) -> AuthError:
    """Map a raw Okta/IDX failure to a message the member can act on. Okta deliberately answers
    both "unknown username" and "wrong password" with the same 'Authentication failed', so the
    friendly text covers both. Unrecognized failures keep the raw text — an ugly true error beats
    a wrong friendly one. The raw text always rides along as root_cause for login_audit."""
    raw = str(exc)
    low = raw.lower()
    if ("authentication failed" in low or "credentials are invalid" in low
            or "no account with" in low or "incorrect username or password" in low):
        return AuthError(
            "That username or password is incorrect. It's the same Church Account you use for "
            "LCR / churchofjesuschrist.org — please check both and try again.",
            kind="bad_credentials", root_cause=raw)
    if "locked" in low:
        return AuthError(
            "This Church Account is temporarily locked (too many attempts). Unlock it at "
            "churchofjesuschrist.org, then sign in here again.",
            kind="account_locked", root_cause=raw)
    return AuthError(f"Sign-in failed: {raw}", root_cause=raw)


# In-process LCR outage tracker (single broker instance, best-effort): consecutive identity-leg
# failures across DISTINCT usernames mean LCR itself is down, not one weird account — tell users
# since when, and surface it on /health. Reset by any full-identity success.
_LCR_OUTAGE: dict = {"first_fail": None, "users": set()}
_OUTAGE_STALE_S = 1800  # forget a stale streak: a quiet half hour means new failures are new news


def _note_lcr_identity(ok: bool, username: str) -> None:
    now = time.time()
    if ok:
        _LCR_OUTAGE["first_fail"] = None
        _LCR_OUTAGE["users"] = set()
        return
    first = _LCR_OUTAGE["first_fail"]
    if first is None or now - first > _OUTAGE_STALE_S:
        _LCR_OUTAGE["first_fail"] = now
        _LCR_OUTAGE["users"] = set()
    _LCR_OUTAGE["users"].add((username or "?").lower())


def lcr_outage_since() -> float | None:
    """Epoch seconds of the first failure of the CURRENT outage window, or None when healthy.
    Degraded only once 2+ distinct accounts failed — one user can be one weird account."""
    first = _LCR_OUTAGE["first_fail"]
    if first is None or len(_LCR_OUTAGE["users"]) < 2 or time.time() - first > _OUTAGE_STALE_S:
        return None
    return first


def _outage_suffix() -> str:
    since = lcr_outage_since()
    if since is None:
        return ""
    return time.strftime(" (LCR has been failing for everyone since %H:%M UTC.)", time.gmtime(since))


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
    on the code screen with no code arriving). Nested choices resolve by PREFERENCE, not first-option:
    our UI is code-entry, so for methodType we pick `totp` (Okta Verify: a push challenge can't be
    answered with a typed code) then `sms`, falling back to the first option (phone: sms vs voice).
    Values are opaque ids/method-types — never the phone number or email itself."""
    form = opt.get("value", {}).get("form", {}).get("value", [])
    obj: dict = {}
    for f in form:
        name = f.get("name")
        if not name:
            continue
        if "value" in f:
            obj[name] = f["value"]
        elif f.get("options"):
            choices = [o.get("value") for o in f["options"]
                       if isinstance(o, dict) and "value" in o]
            if not choices:
                continue
            preferred = next((want for want in ("totp", "sms") if want in choices), None) \
                if name == "methodType" else None
            obj[name] = preferred if preferred is not None else choices[0]
    return obj


def _factors(remediation: dict, types: dict[str, str] | None = None,
             keep_password: bool = False) -> list[dict]:
    """Extract selectable 2nd-factor options from an IDX select. Each entry carries:
      - id/label/method: the client-facing summary (the unchanged shape the apps already render),
      - type: the Okta factor key (okta_email/google_otp/phone_number/…) for logging,
      - _auth: the FULL authenticator body to POST on select (see `_authenticator_object`).
    The password option is dropped by default (it's the primary factor, not a 2nd factor) —
    EXCEPT in a passwordless-lane MFA continuation (keep_password=True): after the emailed code,
    Okta demands a DISTINCT factor type, and for Church accounts that menu is effectively the
    password (phone/TOTP share email's possession type; webauthn can't ride the broker). A kept
    password factor carries method="password" so clients render a password box, not a code box."""
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
            is_password = ftype == "okta_password" or (not ftype and "password" in label.lower())
            if fid and (keep_password or not is_password):
                out.append({"id": fid, "label": label,
                            "method": "password" if is_password else method,
                            "type": ftype, "_auth": auth})
    return out


def _public_factors(factors: list[dict]) -> list[dict]:
    """Strip the internal `_auth`/`type` before returning factors to the client (unchanged wire shape)."""
    return [{"id": f["id"], "label": f["label"], "method": f["method"]} for f in factors]


# Factor types our resumable code-entry flow can actually FINISH. webauthn is structurally
# impossible through the broker (the credential is origin-bound to churchofjesuschrist.org — a
# challenge we start can never be answered by our app), and an Okta Verify PUSH has no code to
# type. Offering them strands the member on a code screen (2026-06-11: a high counselor picked
# "Security Key or Biometric Authenticator" and dead-ended).
_CODE_FACTOR_TYPES = {"okta_email", "phone_number", "google_otp", "okta_verify"}
_UNSUPPORTED_METHODS = {"webauthn", "push", "signed_nonce"}
_UNSUPPORTED_LABEL_HINTS = ("security key", "biometric", "passkey")


def _factor_supported(factor: dict) -> bool:
    """True when our select→type-a-code flow can complete this factor. Unknown types stay OFFERED
    (an unfamiliar menu entry beats locking a leader out; verify now fails friendly) — only
    positively-known-impossible factors are dropped."""
    ftype = (factor.get("type") or "").lower()
    method = (factor.get("method") or "").lower()
    label = (factor.get("label") or "").lower()
    if method in _UNSUPPORTED_METHODS or ftype == "webauthn":
        return False
    if ftype == "okta_verify" and method != "totp":
        return False  # push-only Okta Verify enrollment — nothing to type
    if ftype in _CODE_FACTOR_TYPES:
        return True
    if ftype == "security_question":
        return False  # needs a question/answer UI we don't render
    return not any(hint in label for hint in _UNSUPPORTED_LABEL_HINTS)


def _split_supported(factors: list[dict]) -> tuple[list[dict], list[str]]:
    """(supported factors, PII-safe type names of the dropped ones)."""
    kept = [f for f in factors if _factor_supported(f)]
    dropped = sorted({(f["type"] or f["method"] or "?") for f in factors if not _factor_supported(f)})
    return kept, dropped


_NO_SUPPORTED_FACTORS_MSG = (
    "Your Church Account's verification methods (such as a security key or push approval) "
    "aren't supported here yet. Add a Text message, Email, or Authenticator-app method at "
    "churchofjesuschrist.org under Security, then sign in here again.")


def _challenge_code_field(remediation: dict) -> str | None:
    """The name of the typed-code field a challenge-authenticator expects (`passcode` for
    email/SMS/Google Authenticator, `totp` for Okta Verify), or None when the challenge takes no
    typed code at all (webauthn assertion, push poll). Read from the remediation's own form —
    hardcoding `passcode` is what 401'd an Okta Verify answer. Handles both the direct-form and
    the options[] credential shapes."""
    for field in remediation.get("value", []):
        if field.get("name") != "credentials":
            continue
        names = [f.get("name") for f in field.get("form", {}).get("value", [])]
        for want in ("passcode", "totp"):
            if want in names:
                return want
        for opt in field.get("options", []):
            opt_names = [f.get("name")
                         for f in opt.get("value", {}).get("form", {}).get("value", [])]
            for want in ("passcode", "totp"):
                if want in opt_names:
                    return want
        return None  # a credentials form exists but has no typed-code field
    return "passcode"  # no credentials form visible (minimal/odd payload) — assume the default


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
    """After IDX success: mint an LCR session and read /api/auth/me for identity.
    Retries transient LCR failures (instant 5xx / connection drops) inside the request — see
    establish_and_verify; timeouts are sized so the worst case fits the client's 95s window."""
    me = establish_and_verify(session)
    ident = {
        "email": (me.get("email") or me.get("personalEmail") or "").lower(),
        "name": me.get("name") or me.get("displayName"),
        "cmis_id": me.get("churchCMISID") or me.get("churchCMISUUID"),
        # churchCMISUUID == the LCR person uuid in user_roles.lcr_person_uuid (probe-verified) —
        # the join key that lets a login bind its verified email to its provisioned roles.
        "cmis_uuid": me.get("churchCMISUUID"),
        "username": me.get("preferred_username"),
    }
    logger.info("[auth %s] success: identified %s", login_id, ident.get("username") or ident.get("email"))
    if not ident["email"]:
        logger.warning("[auth %s] no email on /api/auth/me — RLS-by-email won't match", login_id)
    return ident


def _interact_introspect(session: requests.Session, login_id: str) -> tuple[dict, str]:
    """interact -> introspect: open a fresh IDX transaction (shared by the password and the
    passwordless flows). Returns (first payload, pkce_verifier)."""
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
        raise AuthError("The Church sign-in service didn't respond — please try again in a "
                        "moment.", root_cause=f"interact failed ({r.status_code})")
    logger.info("[auth %s] introspect", login_id)
    payload = _idx_post(session, INTROSPECT_URL, {"interactionHandle": r.json()["interaction_handle"]})
    logger.info("[auth %s] introspect -> %s", login_id, _idx_summary(payload))
    return payload, verifier


def _drive_to_password(session: requests.Session, identifier: str, password: str, login_id: str) -> tuple[dict, str]:
    """interact -> introspect -> identify -> (select password) -> answer password.
    Returns (payload, pkce_verifier) so the caller can exchange the interaction_code for tokens."""
    payload, verifier = _interact_introspect(session, login_id)

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
                 "cmis_id": cached.get("cmis_id"), "cmis_uuid": cached.get("cmis_uuid"),
                 "username": cached.get("username"),
                 "login_username": username, "unit_number": cached.get("unit_number"),
                 "stake_name": cached.get("stake_name"),
                 "has_calling": cached.get("has_calling"), "cached": True}
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
        kind, root = classify_lcr_failure(exc)
        _note_lcr_identity(False, username)
        dump_debug("broker_identity_error", login_id=login_id, kind=kind, root_cause=root,
                   error=str(exc))
        obs.event("login.complete", correlation_id=cid, status="error", kind=kind,
                  duration_ms=round((time.time() - t0) * 1000, 1), message=root[:200])
        # Per-mode honesty: a hard 5xx is LCR's outage (not this account, not this app); a rejected
        # SSO is account/session-shaped; everything else keeps the "slow or briefly down" framing.
        if kind == "lcr_5xx":
            msg = ("Your password was accepted, but the Church's LCR system is returning errors "
                   "right now — LCR itself appears to be down. This isn't about your account or "
                   "permissions; please try again later.")
        elif kind == "sso_rejected":
            msg = ("Your Church sign-in worked, but LCR did not accept the session. Try signing "
                   "in once at lcr.churchofjesuschrist.org, then retry here.")
        else:
            msg = ("Your password was accepted, but the Church directory (LCR) didn't answer when "
                   "we asked who you are — it may be slow or briefly down. Please try again in a "
                   "minute.")
        raise IdentityError(msg + _outage_suffix(), kind=kind, root_cause=root,
                            username=username) from exc
    _note_lcr_identity(True, username)
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
        raise friendly_auth_error(exc) from exc

    if "successWithInteractionCode" in payload:
        ident = _finish_success(session, payload, verifier, login_id, cid, _t0, username,
                                want_refresh_token, allow_cached_identity)
        return {"status": "success", "identity": ident, "cookies": serialize_cookies(session)}

    rems = _remediations(payload)
    types = _authenticator_types(payload)
    # MFA shape A: Okta offers a list of 2nd-factor authenticators to choose from. Only factors our
    # code-entry flow can FINISH are offered (a webauthn/push entry on the menu is a guaranteed
    # dead-end — see _factor_supported); the dropped types are logged + carried in the result so
    # the audit row names exactly what an affected account had.
    if "select-authenticator-authenticate" in rems and _factors(rems["select-authenticator-authenticate"], types):
        all_factors = _factors(rems["select-authenticator-authenticate"], types)
        factors, dropped = _split_supported(all_factors)
        offered_types = [f["type"] or f["method"] or "?" for f in factors]
        logger.info("[auth %s] MFA required (shape A); factor_types=%s dropped=%s", login_id,
                    offered_types, dropped)
        if not factors:
            dump_debug("broker_mfa_unsupported", login_id=login_id, dropped=dropped,
                       summary=_idx_summary(payload))
            raise AuthError(_NO_SUPPORTED_FACTORS_MSG, kind="mfa_unsupported",
                            root_cause=f"only unsupported MFA factors enrolled: {dropped}",
                            username=username)
        _store_pending(login_id, session, payload, verifier, factors, username)
        return {"status": "mfa_required", "login_id": login_id,
                "factors": _public_factors(factors),
                "factor_types": offered_types, "dropped_factor_types": dropped}
    # MFA shape B: single-factor — Okta went straight to the code challenge (often after auto-sending
    # an email/SMS code). Surface a generic factor so the app shows the code field; select_factor is a
    # no-op (the code is already pending) and verify_mfa submits it. (Previously this raised "stuck".)
    # A challenge that takes no typed code (webauthn/push) is refused up front instead of presenting
    # a code field that can never succeed.
    if "challenge-authenticator" in rems:
        if _challenge_code_field(rems["challenge-authenticator"]) is None:
            ch_types = sorted(set(types.values()))
            logger.warning("[auth %s] shape-B challenge takes no typed code; types=%s",
                           login_id, ch_types)
            dump_debug("broker_mfa_unsupported", login_id=login_id, shape="B", types=ch_types,
                       summary=_idx_summary(payload))
            raise AuthError(_NO_SUPPORTED_FACTORS_MSG, kind="mfa_unsupported",
                            root_cause=f"shape-B non-code challenge: {ch_types}",
                            username=username)
        _store_pending(login_id, session, payload, verifier, [], username)
        logger.info("[auth %s] MFA required (shape B); single-factor code challenge, types=%s",
                    login_id, sorted(set(types.values())))
        return {"status": "mfa_required", "login_id": login_id,
                "factors": [{"id": "pending", "label": "your verification method", "method": "otp"}],
                "factor_types": sorted(set(types.values()))}
    # Unexpected — log the full PII-safe shape so the next stuck login is diagnosable. Common causes:
    # the account's only factor needs enrollment (`enroll-authenticator` / `select-authenticator-enroll`),
    # or a remediation we don't drive yet. The IDX `messages` (if any) usually name the real reason.
    summary = _idx_summary(payload)
    msg = _idx_messages(payload)
    logger.warning("[auth %s] login stuck after password -> %s", login_id, summary)
    dump_debug("broker_login_stuck", login_id=login_id, summary=summary, messages=msg)
    raise AuthError(msg or "We couldn't complete the sign-in. Please check your username and "
                           "password and try again.", username=username)


_EXPIRED_MSG = ("This sign-in attempt expired. Please start over — and enter the code within "
                "a few minutes of receiving it.")


def select_factor(login_id: str, factor_id: str) -> dict:
    """Choose an MFA factor — sends the code (email/SMS/voice) or readies the prompt (TOTP).
    Re-selecting the same factor re-sends the code (the client's "Send a new code")."""
    pend = _PENDING.get(login_id)
    if not pend:
        raise AuthError(_EXPIRED_MSG, kind="mfa_expired")
    session, payload = pend["session"], pend["payload"]
    username = pend.get("username") or ""
    rems = _remediations(payload)
    sel = rems.get("select-authenticator-authenticate")
    if not sel:
        # Single-factor MFA already at the code challenge (code sent at password time) — nothing to
        # select, so the app's auto-send step is a no-op and we go straight to entering the code.
        if "challenge-authenticator" in rems:
            return {"status": "code_sent"}
        raise AuthError("We couldn't send a verification code — please start signing in again.",
                        kind="mfa_no_selection", username=username)
    sel["_stateHandle"] = payload.get("stateHandle")
    # Send the FULL authenticator object (id + methodType + enrollmentId + nested choices) captured at
    # start_login, NOT just {id}. For phone (SMS/voice) factors the `enrollmentId`/`methodType` are
    # required or Okta silently never sends the code — the exact failure that strands a member on the
    # code screen. Fall back to {id} only if we somehow don't have the stored form (older pending).
    factor = next((f for f in pend.get("factors", []) if f["id"] == factor_id), None)
    auth_obj = (factor or {}).get("_auth") or {"id": factor_id}
    ftype = (factor or {}).get("type") or "?"
    # The label is Okta's own masked destination ("+1 XXX-XX34") — logging it lets a "no text ever
    # arrives" report be checked against a stale enrolled number without asking the member.
    logger.info("[auth %s] select MFA factor type=%s label=%r fields=%s",
                login_id, ftype, (factor or {}).get("label") or "?", sorted(auth_obj))
    try:
        new_payload = _follow(session, sel, {"authenticator": auth_obj})
    except Exception as exc:  # noqa: BLE001 — Okta rejected the select itself
        err_payload = getattr(exc, "payload", None) or {}
        if err_payload.get("stateHandle") and err_payload.get("remediation"):
            pend["payload"] = err_payload
            pend["ts"] = time.time()
        msg = _idx_messages(err_payload)
        dump_debug("broker_select_error", login_id=login_id, factor_type=ftype, error=str(exc))
        raise AuthError(msg or "We couldn't start that verification method — please try a "
                               "different one.", kind="mfa_select_failed", root_cause=str(exc),
                        username=username, factor_type=ftype) from exc
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
        raise AuthError(msg or "We couldn't start that verification method — please try a "
                               "different one.", kind="mfa_select_failed",
                        username=username, factor_type=ftype)
    # A challenge that takes no typed code (webauthn assertion / push approval) would strand the
    # member on a code screen — refuse it now, while they can still pick another method. Defense in
    # depth behind the start_login menu filter (covers unknown factor types we chose to keep).
    ch = new_rems.get("challenge-authenticator")
    if ch is not None and _challenge_code_field(ch) is None:
        logger.warning("[auth %s] selected factor %s yields a non-code challenge", login_id, ftype)
        dump_debug("broker_select_non_code", login_id=login_id, factor_type=ftype,
                   summary=_idx_summary(new_payload))
        raise AuthError("That verification method isn't supported in this app yet — please "
                        "choose a different one.", kind="mfa_unsupported",
                        username=username, factor_type=ftype)
    pend["payload"] = new_payload
    pend["selected_type"] = ftype
    pend["ts"] = time.time()
    return {"status": "code_sent"}


# Per-factor guidance for a rejected code: with several methods enrolled, the most common failure
# is a RIGHT-LOOKING code from the WRONG source — an authenticator-app code typed into a text
# challenge, or an earlier text's code (the 2026-06-11 case: two failures, each ~5s after the SMS
# send; the identical timing SUCCEEDED for an account whose only code source was the fresh text).
_BAD_CODE_HINTS = {
    "phone_number": "Use the 6-digit code from the newest text we just sent — not a code from an "
                    "authenticator app or an earlier text. Tap 'Send a new code' for a fresh one.",
    "google_otp": "Use the code currently showing in your authenticator app.",
    "okta_verify": "Use the code currently showing in your Okta Verify app.",
    "okta_email": "Use the code from the newest email — it can take a minute to arrive.",
}


def _classify_mfa_failure(raw: str, messages: str, *, username: str, factor_type: str) -> AuthError:
    """Map a failed MFA answer to a friendly, ACTIONABLE error. Works from the IDX messages
    (now extracted from nested/field-level blocks too — a wrong code answers 401 with the message
    inside the passcode FIELD); the raw text rides along as root_cause for login_audit. The
    fallback is a generic friendly retry message, never the raw payload (a member saw a raw IDX
    JSON wall on 2026-06-11 and reasonably gave up)."""
    low = (messages or raw).lower()
    if "invalid code" in low or "invalid passcode" in low or "incorrect" in low:
        hint = _BAD_CODE_HINTS.get(factor_type,
                                   "Request a new code and enter it as soon as it arrives.")
        return AuthError(f"That code wasn't accepted — it may be mistyped or expired. {hint}",
                         kind="mfa_bad_code",
                         root_cause=messages or raw, username=username, factor_type=factor_type)
    if "locked" in low or "too many" in low:
        return AuthError("Too many attempts — this Church Account is temporarily locked. Unlock "
                         "it at churchofjesuschrist.org, then sign in here again.",
                         kind="mfa_locked", root_cause=messages or raw,
                         username=username, factor_type=factor_type)
    if "expired" in low:
        return AuthError(_EXPIRED_MSG, kind="mfa_expired", root_cause=messages or raw,
                         username=username, factor_type=factor_type)
    return AuthError(messages or "We couldn't verify that code. Request a new code and try "
                                 "again.", kind="mfa_other", root_cause=raw,
                     username=username, factor_type=factor_type)


def _bump_mfa_fail(pend: dict, login_id: str, username: str, ftype: str) -> None:
    """Count a failed code attempt and, after _MFA_MAX_FAILS, drop the pending login and raise a
    terminal 'start over' error — closing the BACKEND-01 brute-force window (a failed verify
    otherwise refreshed and kept the pending alive forever)."""
    pend["fails"] = pend.get("fails", 0) + 1
    if pend["fails"] >= _MFA_MAX_FAILS:
        _PENDING.pop(login_id, None)
        for k in [k for k, v in _OTP_BY_IDENTIFIER.items() if v == login_id]:
            _OTP_BY_IDENTIFIER.pop(k, None)
        raise AuthError("Too many incorrect codes — please start the sign-in again.",
                        kind="mfa_locked", username=username, factor_type=ftype)


def verify_mfa(login_id: str, code: str, *, want_refresh_token: bool = True,
               allow_cached_identity: bool = False) -> dict:
    """Submit the MFA code and finish login (same fast-lane/full-path tail as start_login).
    The pending login SURVIVES a failed verify (state refreshed from the failure payload), so a
    member can retry or request a new code without redoing the password."""
    pend = _PENDING.get(login_id)
    if not pend:
        raise AuthError(_EXPIRED_MSG, kind="mfa_expired")
    session, payload = pend["session"], pend["payload"]
    verifier = pend.get("verifier", "")
    username = pend.get("username") or ""
    ftype = pend.get("selected_type") or ""
    rems = _remediations(payload)
    ch = rems.get("challenge-authenticator")
    if not ch:
        raise AuthError("Please choose a verification method first.", kind="mfa_no_challenge",
                        username=username)
    ch["_stateHandle"] = payload.get("stateHandle")
    # People paste/type codes with spaces or hyphens ("123 456"); Okta wants bare digits.
    code = re.sub(r"[\s\-]", "", code or "")
    if not code:
        raise AuthError("Enter the verification code first.", kind="mfa_bad_code",
                        username=username, factor_type=ftype)
    # Answer with the field THIS challenge declares (passcode vs totp) — Okta Verify's TOTP
    # rejects {"passcode": ...} outright (the 2026-06-11 class of failure, hardcoded until now).
    field = _challenge_code_field(ch) or "passcode"
    logger.info("[auth %s] verify MFA code (field=%s type=%s)", login_id, field, ftype or "?")
    try:
        payload = _follow(session, ch, {"credentials": {field: code}}, redact=True)
    except Exception as exc:  # noqa: BLE001
        err_payload = getattr(exc, "payload", None) or {}
        # Refresh the pending state from the FAILURE payload — Okta may rotate the stateHandle on
        # a rejected answer, and a retry against the stale one fails regardless of the code.
        if err_payload.get("stateHandle") and err_payload.get("remediation"):
            pend["payload"] = err_payload
            pend["ts"] = time.time()
        messages = _idx_messages(err_payload)
        dump_debug("broker_mfa_error", login_id=login_id, factor_type=ftype, error=str(exc),
                   messages=messages,
                   summary=_idx_summary(err_payload) if err_payload else None)
        classified = _classify_mfa_failure(str(exc), messages, username=username, factor_type=ftype)
        _bump_mfa_fail(pend, login_id, username, ftype)  # may raise mfa_locked (and drop the pending)
        raise classified from exc
    logger.info("[auth %s] post-verify -> %s", login_id, _idx_summary(payload))
    if "successWithInteractionCode" not in payload:
        # The answer may have been ACCEPTED with another factor still owed — an MFA-enabled
        # account in the passwordless lane (2026-06-12: the operator enabled MFA and every
        # correct emailed code came back "couldn't verify"). Hand off to the factor step
        # instead of classifying a verified step as a failure.
        cont = _mfa_continuation(login_id, pend, payload, username)
        if cont is not None:
            return cont
        # Keep the (refreshed) state so a wrong-code retry uses the latest stateHandle, not a stale one.
        pend["payload"] = payload
        pend["ts"] = time.time()
        classified = _classify_mfa_failure("MFA answer accepted but login did not complete",
                                           _idx_messages(payload), username=username, factor_type=ftype)
        _bump_mfa_fail(pend, login_id, username, ftype)  # may raise mfa_locked (and drop the pending)
        raise classified
    from backend import observability as obs
    cid = obs.new_correlation_id()
    # t0 = now: times only this completion leg (the gap since start_login is human typing time).
    ident = _finish_success(session, payload, verifier, login_id, cid, time.time(),
                            pend.get("username") or "", want_refresh_token, allow_cached_identity)
    cookies = serialize_cookies(session)
    _PENDING.pop(login_id, None)
    return {"status": "success", "identity": ident, "cookies": cookies}


def _mfa_continuation(login_id: str, pend: dict, payload: dict, username: str) -> dict | None:
    """A verified step that did NOT finish the login but offers the NEXT factor is a
    CONTINUATION, not a failure. Seen when an MFA-enabled account uses the passwordless lane:
    the emailed code satisfies the possession factor, then Okta demands a DISTINCT factor type
    — for Church accounts that menu is effectively the password (live 2026-06-12: post-verify
    `select-authenticator-authenticate` + password challenge, no messages). Returns the same
    mfa_required hand-off shape as start_login (the client re-enters the factor step with the
    SAME login_id, so /auth/mfa/select + /auth/mfa/verify just work), or None when the payload
    is a plain failure (messages present / nothing actionable) — the caller classifies those.
    Raises mfa_unsupported when every remaining factor is undriveable (e.g. webauthn-only)."""
    if _idx_messages(payload):
        return None  # an error message means the answer was rejected, not accepted-and-continued
    rems = _remediations(payload)
    sel = rems.get("select-authenticator-authenticate")
    ch = rems.get("challenge-authenticator")
    types = _authenticator_types(payload)
    if sel is not None:
        all_factors = _factors(sel, types, keep_password=True)
        factors, dropped = _split_supported(all_factors)
        if all_factors and not factors:
            dump_debug("broker_mfa_continuation_unsupported", login_id=login_id, dropped=dropped,
                       summary=_idx_summary(payload))
            raise AuthError(_NO_SUPPORTED_FACTORS_MSG, kind="mfa_unsupported",
                            root_cause=f"continuation offers only unsupported factors: {dropped}",
                            username=username)
        if factors:
            logger.info("[auth %s] MFA continuation (next factor); factor_types=%s dropped=%s",
                        login_id, [f["type"] or f["method"] or "?" for f in factors], dropped)
            pend.update(payload=payload, factors=factors, ts=time.time())
            return {"status": "mfa_required", "login_id": login_id,
                    "factors": _public_factors(factors),
                    "factor_types": [f["type"] or f["method"] or "?" for f in factors],
                    "dropped_factor_types": dropped}
    if ch is not None and _challenge_code_field(ch) is not None:
        # Already at the next challenge (Okta auto-selected) — shape-B-style hand-off. Name a
        # password challenge so clients render a password box, not a 6-digit code box.
        cur = (payload.get("currentAuthenticatorEnrollment", {}).get("value", {}) or {})
        is_password = (cur.get("key") or "") == "okta_password"
        logger.info("[auth %s] MFA continuation (auto-challenged %s)", login_id,
                    cur.get("key") or "factor")
        pend.update(payload=payload, factors=[], ts=time.time())
        factor = ({"id": "pending", "label": "your Church Account password", "method": "password"}
                  if is_password else
                  {"id": "pending", "label": "your verification method", "method": "otp"})
        return {"status": "mfa_required", "login_id": login_id, "factors": [factor],
                "factor_types": [cur.get("key") or "?"]}
    return None


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
        raise AuthError("We couldn't verify the sign-in session from the app — please try "
                        "signing in again.", root_cause=str(exc)) from exc


# --- passwordless email-code login (OTP as the PRIMARY factor) ----------------------------------
# Whether a Church Account may sign in with an EMAILED CODE instead of its password is the Okta
# org's policy, per account: identify (no password sent) either offers an okta_email authenticator
# on the primary select menu (passwordless enabled), or only Password (the default in every flow
# captured so far). otp_start finds out honestly — it answers "code_sent" only after Okta ACCEPTED
# the factor select (the select is what sends the email); a password-first account gets an
# actionable error, never a phantom "code sent". Pending state lives in the same _PENDING store as
# the password+MFA flow (keyed additionally by identifier), so otp_verify IS verify_mfa — the same
# declared-field code answer, friendly failure classification, wrong-code retry, and identity tail.

_OTP_BY_IDENTIFIER: dict[str, str] = {}  # normalized identifier -> login_id in _PENDING

_OTP_UNAVAILABLE_MSG = (
    "This Church Account can't sign in with an emailed code — Okta asks for its password first. "
    "Use the Church username option instead; if your account has MFA, an emailed code can still "
    "be your second step.")

# Okta's account-enumeration prevention makes an UNKNOWN identifier wire-indistinguishable from a
# real one (probe-proven 2026-06-12: a bogus identifier gets the same Email+Password menu, the
# email-factor select is accepted, a passcode challenge comes back — and no email is ever sent;
# every code answers "Invalid code"). The Church org matches the USERNAME, not the email address
# (the same account: username → code in 1s, its gmail → phantom). We can't detect the phantom
# server-side, so an email-shaped identifier gets honest guidance instead of a silent dead-end.
_OTP_USERNAME_HINT = (
    "Heads up: codes are sent by Church USERNAME. If no code arrives within a couple of minutes, "
    "what you entered is probably not your username — start over and enter the username you use "
    "at churchofjesuschrist.org (usually not an email address).")

# Okta SILENTLY stops emailing codes after a burst of requests for the same account (observed
# live 2026-06-12: five delivered in 36 minutes, then every accepted select produced no email
# for 40+ minutes — wire-indistinguishable from a normal send). Track sends per identifier so
# the member is told the likely reason instead of hammering "Send a new code" (which extends
# the suppression). In-memory is fine — the broker runs single-instance.
_OTP_SEND_TIMES: dict[str, list[float]] = {}  # identifier -> recent send timestamps
_OTP_THROTTLE_WINDOW = 3600.0
_OTP_THROTTLE_AFTER = 4  # the 4th+ send within the window earns the hint
_OTP_THROTTLE_HINT = (
    "Several codes were requested for this account recently — the Church sign-in service may "
    "quietly pause email delivery for a while. If no code arrives, wait 15-30 minutes before "
    "requesting another, and only enter the NEWEST code.")


def otp_start(identifier: str) -> dict:
    """Begin a PASSWORDLESS login: identify -> find okta_email on the PRIMARY factor menu ->
    select it (the select is what makes Okta send the email). Returns {"status": "code_sent",
    "sent_to": label}. Raises AuthError(kind=otp_unavailable) when the account's policy is
    password-first (the Church default) — the client shows why instead of a code field."""
    _prune()
    # Mappings whose pending login was TTL-pruned are dead — drop them so the map stays bounded.
    for k in [k for k, v in _OTP_BY_IDENTIFIER.items() if v not in _PENDING]:
        _OTP_BY_IDENTIFIER.pop(k, None)
    now = time.time()
    for k in [k for k, ts in _OTP_SEND_TIMES.items()
              if not ts or now - ts[-1] > _OTP_THROTTLE_WINDOW]:
        _OTP_SEND_TIMES.pop(k, None)
    ident = (identifier or "").strip().lower()
    if not ident:
        raise AuthError("Enter your Church username first.", kind="otp_bad_request")
    login_id = _new_login_id()
    # Okta matches the USERNAME only — an email identifier gets the enumeration-prevention
    # phantom flow (code never arrives). Any prior verified login taught us this member's
    # email -> username, so resolve it and identify with the username; an unknown email
    # proceeds as typed (it might BE a username) with the honest hint in the response.
    okta_ident, resolved = ident, False
    if "@" in ident:
        known = identity_cache.username_for_email(ident)
        if known:
            okta_ident, resolved = known, True
            logger.info("[auth %s] otp identifier: email resolved to a cached Church username",
                        login_id)
    session = new_session()
    try:
        payload, verifier = _drive_to_identify(session, okta_ident, login_id)
    except AuthError:
        raise
    except Exception as exc:  # noqa: BLE001
        dump_debug("broker_otp_identify_error", login_id=login_id, error=str(exc))
        raise friendly_auth_error(exc) from exc
    rems = _remediations(payload)
    sel = rems.get("select-authenticator-authenticate")
    factors = _factors(sel, _authenticator_types(payload)) if sel else []
    supported, _dropped = _split_supported(factors)
    email_factor = next((f for f in supported if f.get("type") == "okta_email"), None)
    logger.info("[auth %s] otp primary menu -> %s", login_id, _idx_summary(payload))
    if email_factor is None:
        offered = sorted({f.get("type") or f.get("method") or "?" for f in factors})
        raise AuthError(_OTP_UNAVAILABLE_MSG, kind="otp_unavailable",
                        root_cause=f"primary factors offered: {','.join(offered) or 'password-only'}",
                        username=okta_ident, factor_type="okta_email")
    _store_pending(login_id, session, payload, verifier, factors, okta_ident)
    select_factor(login_id, email_factor["id"])  # raises friendly if Okta rejects the send
    # The map stays keyed by what the member TYPED — otp_verify receives the same identifier.
    old = _OTP_BY_IDENTIFIER.get(ident)
    if old and old != login_id:
        _PENDING.pop(old, None)  # a resend replaces the older challenge — the freshest code wins
    _OTP_BY_IDENTIFIER[ident] = login_id
    res = {"status": "code_sent", "sent_to": email_factor.get("label") or "your email"}
    if "@" in ident and not resolved:
        res["identifier_hint"] = _OTP_USERNAME_HINT
    sends = [t for t in _OTP_SEND_TIMES.get(ident, []) if now - t < _OTP_THROTTLE_WINDOW]
    sends.append(now)
    _OTP_SEND_TIMES[ident] = sends
    if len(sends) >= _OTP_THROTTLE_AFTER:
        res["throttle_hint"] = _OTP_THROTTLE_HINT
    return res


def _drive_to_identify(session: requests.Session, identifier: str, login_id: str) -> tuple[dict, str]:
    """interact -> introspect -> identify, NO password: stops at whatever Okta offers next (the
    primary authenticator menu, or a password challenge). Returns (payload, pkce_verifier)."""
    payload, verifier = _interact_introspect(session, login_id)
    for _ in range(4):
        rems = _remediations(payload)
        sh = payload.get("stateHandle")
        for rr in rems.values():
            rr["_stateHandle"] = sh
        if "identify" not in rems:
            break
        logger.info("[auth %s] otp identify", login_id)
        # rememberMe=True for the same reason as the password flow: the Okta session's own
        # lifetime is the only lever on how long a stored credential keeps re-minting.
        payload = _follow(session, rems["identify"], {"identifier": identifier, "rememberMe": True})
    return payload, verifier


def otp_verify(identifier: str, code: str, *, want_refresh_token: bool = True,
               allow_cached_identity: bool = False) -> dict:
    """Finish a passwordless login. The pending state IS an MFA-style code challenge, so this
    delegates to verify_mfa — a wrong code keeps the pending alive for a retry (exactly like MFA),
    and success runs the same identity tail (cache fast-lane / token exchange / LCR identity)."""
    ident = (identifier or "").strip().lower()
    login_id = _OTP_BY_IDENTIFIER.get(ident, "")
    if not login_id or login_id not in _PENDING:
        _OTP_BY_IDENTIFIER.pop(ident, None)
        raise AuthError(_EXPIRED_MSG, kind="mfa_expired", username=ident)
    # When the typed email RESOLVED to a cached username at start, the pending carries that
    # username — codes really were sent, so a rejected code there is a typo, not the phantom.
    unresolved_email = "@" in ident and (_PENDING[login_id].get("username") or ident) == ident
    try:
        res = verify_mfa(login_id, code, want_refresh_token=want_refresh_token,
                         allow_cached_identity=allow_cached_identity)
    except IdentityError:
        raise
    except AuthError as exc:
        kind = getattr(exc, "kind", "")
        # "Please choose a verification method first" is MFA-menu copy — the OTP lane HAS no
        # menu (the Email factor is auto-selected). It surfaces here when a failed verify left
        # a challenge-less pending payload (Ken Packer hit it retrying codes the phantom flow
        # had rejected, 2026-06-12). Name the actual way out: a fresh code.
        if kind == "mfa_no_challenge":
            msg = ("This code request is no longer active — tap 'Send a new code' and enter "
                   "the newest code.")
            if unresolved_email:
                msg += " " + _OTP_USERNAME_HINT
            raise AuthError(msg, kind=kind, root_cause=exc.root_cause,
                            username=exc.username or ident,
                            factor_type=exc.factor_type) from exc
        # A rejected code on an UNRESOLVED email-shaped identifier is exactly what Okta's
        # enumeration-prevention phantom flow produces (no email was ever sent; every code is
        # "invalid"). Append the username guidance so the member isn't stuck retyping codes
        # that can't work.
        if unresolved_email and kind == "mfa_bad_code":
            raise AuthError(f"{exc} {_OTP_USERNAME_HINT}", kind=exc.kind,
                            root_cause=exc.root_cause, username=exc.username or ident,
                            factor_type=exc.factor_type) from exc
        raise
    _OTP_BY_IDENTIFIER.pop(ident, None)
    return res

# (The background cache refresh lives in enroll.refresh_cached_identity — it also re-reads the
# UNIT via user_context, which a /api/auth/me-only refresher here couldn't.)
