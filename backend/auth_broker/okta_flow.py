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

_PENDING: dict[str, dict] = {}          # login_id -> {session, payload, ts}
_TTL = 600                              # 10 min to complete an MFA challenge


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
        raise AuthError("The Church sign-in service didn't respond — please try again in a "
                        "moment.", root_cause=f"interact failed ({r.status_code})")
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
    logger.info("[auth %s] select MFA factor type=%s fields=%s", login_id, ftype, sorted(auth_obj))
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


def _classify_mfa_failure(raw: str, messages: str, *, username: str, factor_type: str) -> AuthError:
    """Map a failed MFA answer to a friendly, ACTIONABLE error. Works from the IDX messages
    (now extracted from nested/field-level blocks too — a wrong code answers 401 with the message
    inside the passcode FIELD); the raw text rides along as root_cause for login_audit. The
    fallback is a generic friendly retry message, never the raw payload (a member saw a raw IDX
    JSON wall on 2026-06-11 and reasonably gave up)."""
    low = (messages or raw).lower()
    if "invalid code" in low or "invalid passcode" in low or "incorrect" in low:
        return AuthError("That code wasn't accepted — it may be mistyped or expired. Request a "
                         "new code and enter it as soon as it arrives.", kind="mfa_bad_code",
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
        raise _classify_mfa_failure(str(exc), messages, username=username,
                                    factor_type=ftype) from exc
    logger.info("[auth %s] post-verify -> %s", login_id, _idx_summary(payload))
    if "successWithInteractionCode" not in payload:
        # Keep the (refreshed) state so a wrong-code retry uses the latest stateHandle, not a stale one.
        pend["payload"] = payload
        pend["ts"] = time.time()
        raise _classify_mfa_failure("MFA answer accepted but login did not complete",
                                    _idx_messages(payload), username=username, factor_type=ftype)
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
        raise AuthError("We couldn't verify the sign-in session from the app — please try "
                        "signing in again.", root_cause=str(exc)) from exc


# --- Email-first OTP authentication (no password required) ---

_OTP_SESSIONS: dict[str, dict] = {}  # email -> {session, payload, verifier, ts}
_OTP_TTL = 600  # 10 minutes

def otp_start(email: str, enroll: bool = False) -> dict:
    """Initiate Church account authentication via email OTP. Returns available factors or error.
    Accepts either an email address or username; Okta will authenticate whichever works."""
    from lcr_client.okta_login import new_session
    from backend import observability as obs

    email = (email or "").strip().lower()
    if not email:
        raise AuthError("An email address or username is required.")

    login_id = _new_login_id()
    cid = obs.new_correlation_id()
    session = new_session()
    t0 = time.time()

    try:
        # Use email as the identifier (most Okta orgs support email login)
        with obs.span("login.otp_identify", correlation_id=cid, endpoint="okta"):
            payload, verifier = _drive_to_factor_select(session, email, login_id)
    except AuthError as e:
        logger.warning("[auth %s] otp identify failed: %s", login_id, str(e))
        raise AuthError(str(e)) from e
    except Exception as e:  # noqa: BLE001
        logger.exception("[auth %s] otp identify error", login_id)
        dump_debug("broker_otp_error", login_id=login_id, error=str(e))
        raise AuthError(f"OTP authentication failed: {str(e)[:200]}") from e

    # Extract available factors from the select-authenticator-authenticate remediation
    rems = _remediations(payload)
    select_auth_rem = rems.get("select-authenticator-authenticate", {})
    auth_types = _authenticator_types(payload)
    factors = _factors(select_auth_rem, auth_types)

    # Store session for verify step
    _OTP_SESSIONS[email] = {"session": session, "payload": payload, "verifier": verifier,
                            "login_id": login_id, "cid": cid, "t0": t0, "ts": time.time()}

    return {"ok": True, "factors": factors}


def _drive_to_factor_select(session: requests.Session, email: str, login_id: str) -> tuple:
    """Identify via email and drive the IDX flow until a factor-selection state."""
    from lcr_client.okta_login import (
        _idx_post, _remediations, _follow, INTROSPECT_URL, CLIENT_ID, SCOPE,
        REDIRECT_URI, ISSUER)
    import secrets

    logger.info("[auth %s] otp interact + identify", login_id)
    verifier, challenge = _pkce()

    # Start a new IDX transaction (like the password flow does)
    interact_resp = session.post(
        f"{ISSUER}/v1/interact",
        data={"client_id": CLIENT_ID, "scope": SCOPE,
              "redirect_uri": REDIRECT_URI, "response_type": "code",
              "state": secrets.token_hex(16), "code_challenge": challenge,
              "code_challenge_method": "S256"},
        timeout=60)
    if interact_resp.status_code >= 400:
        raise AuthError(f"Okta interact failed: {interact_resp.status_code}")

    interaction_handle = interact_resp.json()["interaction_handle"]

    # Introspect to get initial state
    payload = _idx_post(session, INTROSPECT_URL, {"interactionHandle": interaction_handle})
    state_handle = payload.get("stateHandle")

    for attempt in range(8):
        rems = _remediations(payload)
        for r in rems.values():
            r["_stateHandle"] = state_handle

        if "identify" in rems:
            logger.info("[auth %s] otp identify (identifier=%s)", login_id, email)
            payload = _follow(session, rems["identify"], {"identifier": email, "rememberMe": False})
            state_handle = payload.get("stateHandle")
            continue

        if "select-authenticator-authenticate" in rems:
            logger.info("[auth %s] otp: factor selection available", login_id)
            return payload, verifier

        # Unexpected state
        logger.warning("[auth %s] otp unexpected state: %s", login_id, sorted(rems.keys()))
        raise AuthError(f"Unexpected OTP flow state: {sorted(rems.keys())}")

    raise AuthError("OTP flow did not reach factor selection within step budget")


def otp_verify(email: str, code: str, enroll: bool = False,
               want_refresh_token: bool = True, allow_cached_identity: bool = False) -> dict:
    """Verify OTP code and complete authentication."""
    from lcr_client.okta_login import _follow, _authenticator_types
    from backend import observability as obs

    email = (email or "").strip().lower()
    code = (code or "").strip()

    if not code:
        raise AuthError("A verification code is required.")

    stored = _OTP_SESSIONS.get(email)
    if not stored:
        raise AuthError("The OTP session has expired. Please request a new code.")

    # Prune old sessions
    now = time.time()
    cutoff = now - _OTP_TTL
    for k in [k for k, v in _OTP_SESSIONS.items() if v.get("ts", 0) < cutoff]:
        _OTP_SESSIONS.pop(k, None)

    if not stored or stored["ts"] < cutoff:
        raise AuthError("The OTP session has expired. Please request a new code.")

    session = stored["session"]
    payload = stored["payload"]
    login_id = stored["login_id"]
    cid = stored["cid"]
    t0 = stored["t0"]

    try:
        # Select email/OTP factor (prefer email, then google_otp, then first available)
        auth_types = _authenticator_types(payload)
        factors = _factors(payload.get("currentAuthenticatorEnroll", {}))
        if not factors:
            factors = _factors(payload.get("currentAuthenticator", {}))

        email_factor = next((f for f in factors if "email" in f.get("type", "").lower()), None)
        otp_factor = next((f for f in factors if "otp" in f.get("type", "").lower()), None)
        selected = email_factor or otp_factor or (factors[0] if factors else None)

        if not selected:
            raise AuthError("No OTP factors are available for your account.")

        with obs.span("login.otp_select", correlation_id=cid):
            logger.info("[auth %s] otp select factor: %s", login_id, selected.get("label"))
            payload = _follow(session, payload.get("currentAuthenticator", {}),
                             {"authenticator": selected.get("_auth", {"id": selected["id"]})})

        # Answer with the code
        state = _code_input(payload)
        if not state:
            raise AuthError("The OTP factor does not support code entry.")

        with obs.span("login.otp_answer", correlation_id=cid):
            logger.info("[auth %s] otp answer code", login_id)
            payload = _follow(session, state, {"credentials": {"passcode": code}})

        if "successWithInteractionCode" not in payload:
            _OTP_SESSIONS[email] = {"session": session, "payload": payload, "verifier": stored["verifier"],
                                    "login_id": login_id, "cid": cid, "t0": t0, "ts": time.time()}
            msgs = _idx_messages(payload)
            raise AuthError(_user_message(msgs) or "That code didn't work. Please try again.")

        # Success: complete the authentication
        username = email  # use email as the username for caching/logging
        ident = _finish_success(session, payload, stored["verifier"], login_id, cid, t0,
                               username, want_refresh_token, allow_cached_identity)
        cookies = serialize_cookies(session)
        _OTP_SESSIONS.pop(email, None)
        return {"status": "success", "identity": ident, "cookies": cookies}

    except AuthError:
        raise
    except Exception as e:  # noqa: BLE001
        logger.exception("[auth %s] otp verify error", login_id)
        dump_debug("broker_otp_verify_error", login_id=login_id, error=str(e))
        raise AuthError("Code verification failed. Please try again.") from e


def _user_message(messages: list[str]) -> str | None:
    """Extract the most relevant user-facing message from IDX responses."""
    for msg in messages:
        msg_lower = msg.lower()
        if "incorrect" in msg_lower or "invalid" in msg_lower or "doesn't match" in msg_lower:
            return msg
    return messages[0] if messages else None

# (The background cache refresh lives in enroll.refresh_cached_identity — it also re-reads the
# UNIT via user_context, which a /api/auth/me-only refresher here couldn't.)
