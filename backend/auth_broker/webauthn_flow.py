"""
Passwordless passkey login (server-side WebAuthn) for the broker.

Two ceremonies, mirroring the broker's other flows (stateful, in-memory challenge keyed by a
short-lived handle):

  register  — an already-signed-in user binds a passkey to their email. begin() returns options;
              the browser creates a platform/roaming credential; complete() verifies the attestation
              and stores the public key in webauthn_credentials (migration 0023).
  login     — anyone clicks "sign in with a passkey". begin() returns a discoverable-credential
              challenge; the browser signs it (biometric unlocks the private key); complete()
              verifies the assertion against the stored public key, then mints a Supabase session
              OTP (session_mint) for that credential's email — the app verifyOtp's into a session.

No password is ever involved. The public key + credential id are not secrets; the table is locked
to the service role anyway. RP id / origins are env-config (default = the production web domain).
"""

from __future__ import annotations

import json
import os
import re
import secrets
import time
from datetime import datetime, timezone

import requests

from lcr_client.logging_setup import get_logger
from backend.auth_broker import admin, session_mint

logger = get_logger()

RP_ID = os.environ.get("WEBAUTHN_RP_ID", "membercovenantpath.org")
RP_NAME = "Covenant Path"
ORIGINS = [o.strip() for o in os.environ.get(
    "WEBAUTHN_ORIGINS", "https://app.membercovenantpath.org").split(",") if o.strip()]

_TTL = 300  # 5 min to complete a ceremony
_PENDING: dict[str, dict] = {}  # handle -> {challenge: bytes, email: str|None, ts: float}


class PasskeyError(RuntimeError):
    pass


def _prune() -> None:
    cutoff = time.time() - _TTL
    for k in [k for k, v in _PENDING.items() if v["ts"] < cutoff]:
        _PENDING.pop(k, None)


def _handle() -> str:
    return secrets.token_urlsafe(12)


_B64URL = re.compile(r"^[A-Za-z0-9_-]{16,512}$")  # WebAuthn credential ids are base64url


def _safe_cred_id(cred_id: str) -> str:
    """BACKEND-03: the credential id is attacker-controlled (unauthenticated /webauthn/login/complete)
    and is interpolated into a PostgREST `eq.` filter — require strict base64url so it cannot carry
    filter operators/metacharacters."""
    if not cred_id or not _B64URL.match(cred_id):
        raise PasskeyError("malformed passkey response")
    return cred_id


def _rest(method: str, path: str, **kw):
    # Merge caller headers INTO the service headers — register_complete/login_complete pass their
    # own `headers=` kwarg, which collided with this signature's hardcoded one and 500'd BOTH
    # passkey ceremonies in production (TypeError: multiple values for 'headers'; caught by the
    # A15 fullstack e2e, 2026-06-11).
    headers = {**admin._sb_headers(), **(kw.pop("headers", None) or {})}
    return requests.request(method, f"{admin.SUPABASE_URL}/rest/v1/{path}",
                            headers=headers, timeout=15, **kw)


def _creds_for_email(email: str) -> list[dict]:
    r = _rest("GET", "webauthn_credentials",
              params={"select": "credential_id", "email": f"eq.{email.lower()}"})
    return r.json() if r.status_code == 200 else []


# --- registration (signed-in user binds a passkey) --------------------------

def register_begin(email: str) -> dict:
    _prune()
    from webauthn import generate_registration_options, options_to_json
    from webauthn.helpers import base64url_to_bytes
    from webauthn.helpers.structs import (AuthenticatorSelectionCriteria,
                                          PublicKeyCredentialDescriptor,
                                          ResidentKeyRequirement, UserVerificationRequirement)
    exclude = [PublicKeyCredentialDescriptor(id=base64url_to_bytes(c["credential_id"]))
               for c in _creds_for_email(email)]
    opts = generate_registration_options(
        rp_id=RP_ID, rp_name=RP_NAME, user_name=email, user_display_name=email,
        user_id=email.lower().encode("utf-8"),
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.REQUIRED),  # BACKEND-09: require UV
        exclude_credentials=exclude)
    h = _handle()
    _PENDING[h] = {"challenge": opts.challenge, "email": email.lower(), "ts": time.time()}
    return {"handle": h, "options": json.loads(options_to_json(opts))}


def register_complete(handle: str, credential: dict) -> dict:
    pend = _PENDING.pop(handle, None)
    if not pend:
        raise PasskeyError("registration expired — start over")
    from webauthn import verify_registration_response
    from webauthn.helpers import bytes_to_base64url
    try:
        ver = verify_registration_response(
            credential=json.dumps(credential), expected_challenge=pend["challenge"],
            expected_rp_id=RP_ID, expected_origin=ORIGINS)
    except Exception as exc:  # noqa: BLE001
        raise PasskeyError(f"passkey registration failed: {exc}") from exc
    r = _rest("POST", "webauthn_credentials",
              headers={**admin._sb_headers(), "Content-Type": "application/json",
                       "Prefer": "resolution=merge-duplicates"},
              json={"email": pend["email"], "credential_id": bytes_to_base64url(ver.credential_id),
                    "public_key": bytes_to_base64url(ver.credential_public_key),
                    "sign_count": ver.sign_count})
    if r.status_code >= 300:
        raise PasskeyError(f"could not store passkey ({r.status_code})")
    logger.info("registered passkey for %s", pend["email"])
    return {"status": "registered"}


# --- login (passwordless) ---------------------------------------------------

def login_begin() -> dict:
    _prune()
    from webauthn import generate_authentication_options, options_to_json
    from webauthn.helpers.structs import UserVerificationRequirement
    opts = generate_authentication_options(
        rp_id=RP_ID, user_verification=UserVerificationRequirement.PREFERRED)
    h = _handle()
    _PENDING[h] = {"challenge": opts.challenge, "email": None, "ts": time.time()}
    return {"handle": h, "options": json.loads(options_to_json(opts))}


def login_complete(handle: str, credential: dict) -> dict:
    pend = _PENDING.pop(handle, None)
    if not pend:
        raise PasskeyError("login expired — start over")
    cred_id = _safe_cred_id(credential.get("id") or credential.get("rawId") or "")
    rows = _rest("GET", "webauthn_credentials",
                 params={"select": "*", "credential_id": f"eq.{cred_id}", "limit": "1"})
    recs = rows.json() if rows.status_code == 200 else []
    if not recs:
        raise PasskeyError("unknown passkey — register it in the app first")
    rec = recs[0]
    from webauthn import verify_authentication_response
    from webauthn.helpers import base64url_to_bytes
    try:
        ver = verify_authentication_response(
            credential=json.dumps(credential), expected_challenge=pend["challenge"],
            expected_rp_id=RP_ID, expected_origin=ORIGINS,
            credential_public_key=base64url_to_bytes(rec["public_key"]),
            credential_current_sign_count=rec["sign_count"],
            require_user_verification=True)  # BACKEND-09: a session-minting login must prove UV
    except Exception as exc:  # noqa: BLE001
        raise PasskeyError(f"passkey verification failed: {exc}") from exc
    # BACKEND-09: treat a sign-count regression (cloned authenticator) as a hard failure.
    if rec.get("sign_count") and ver.new_sign_count and ver.new_sign_count <= rec["sign_count"]:
        raise PasskeyError("passkey verification failed: sign-count regression")
    _rest("PATCH", "webauthn_credentials",
          headers={**admin._sb_headers(), "Content-Type": "application/json", "Prefer": "return=minimal"},
          params={"credential_id": f"eq.{cred_id}"},
          json={"sign_count": ver.new_sign_count,
                "last_used_at": datetime.now(timezone.utc).isoformat()})
    logger.info("passkey login verified for %s", rec["email"])
    return session_mint.mint_otp(rec["email"])  # {email, otp} -> app verifyOtp
