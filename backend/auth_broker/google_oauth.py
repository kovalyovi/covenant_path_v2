"""
Per-stake Google Drive OAuth (M7).

A stake leader authorizes once; we store their **envelope-encrypted refresh token** (CP_TOKEN_KEY
vault, same as the LCR delegated credentials) and create + maintain the stake's spreadsheet IN THEIR
Drive — so the platform never owns it (and gets the create capability a 0-storage service account
can't have).

Server-side authorization-code flow through the broker:
  GET /auth/google/start?stake=<id>  -> 302 to Google consent  (signed state binds the stake + nonce)
  GET /auth/google/callback          -> exchange code -> {refresh_token, email} -> encrypt + store

`drive.file` scope only — the app can touch only files it creates, never the rest of the Drive.
No-op until GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET are set on the broker.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from urllib.parse import urlencode

import requests

from backend.credentials import _decrypt_envelope, _encrypt_envelope
from lcr_client.logging_setup import get_logger
from lcr_client.token_store import _load_key

logger = get_logger()

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPES = "https://www.googleapis.com/auth/drive.file openid email"
_STATE_TTL = 300  # signed-state validity (seconds); single-use via _CONSUMED (BACKEND-05)
_CONSUMED: dict[str, float] = {}  # nonce -> consumed-at; a given signed state is redeemable once
_DEFAULT_REDIRECT = "https://covenant-path-broker.onrender.com/auth/google/callback"


class OAuthError(RuntimeError):
    pass


def is_configured() -> bool:
    return bool(os.getenv("GOOGLE_OAUTH_CLIENT_ID") and os.getenv("GOOGLE_OAUTH_CLIENT_SECRET"))


def _cfg() -> tuple[str, str, str]:
    cid = os.getenv("GOOGLE_OAUTH_CLIENT_ID")
    csec = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")
    redirect = os.getenv("GOOGLE_OAUTH_REDIRECT", _DEFAULT_REDIRECT)
    if not cid or not csec:
        raise OAuthError("GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET not set on the broker")
    return cid, csec, redirect


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


# --- CSRF/stake-bound signed state -----------------------------------------

def sign_state(stake_id: str, subject: str | None = None) -> str:
    """HMAC-signed, short-TTL, single-use state binding the OAuth round-trip to one stake (+ a
    nonce, and the initiating user when known — BACKEND-05)."""
    payload = _b64(json.dumps(
        {"s": stake_id, "u": (subject or "").lower(), "n": _b64(os.urandom(12)),
         "e": int(time.time()) + _STATE_TTL}).encode())
    sig = _b64(hmac.new(_load_key(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{sig}"


def verify_state(state: str) -> str:
    """Return the bound stake_id, or raise if the signature is wrong / expired / already used.
    Single-use (BACKEND-05): a signed state is redeemable at most once, so a leaked or replayed
    callback can't re-bind a stake's Drive within the TTL window."""
    try:
        payload, sig = state.split(".", 1)
    except (ValueError, AttributeError):
        raise OAuthError("malformed state")
    expect = _b64(hmac.new(_load_key(), payload.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expect):
        raise OAuthError("state signature mismatch")
    d = json.loads(_unb64(payload))
    if int(d.get("e", 0)) < time.time():
        raise OAuthError("state expired — start over")
    now = time.time()
    for k in [k for k, t in list(_CONSUMED.items()) if now - t > _STATE_TTL]:
        _CONSUMED.pop(k, None)  # prune expired nonces so the map stays bounded
    nonce = d.get("n", "")
    if nonce in _CONSUMED:
        raise OAuthError("this Drive-connect link was already used — start over")
    _CONSUMED[nonce] = now
    return str(d["s"])


# --- OAuth flow ------------------------------------------------------------

def start_url(stake_id: str, subject: str | None = None) -> str:
    cid, _, redirect = _cfg()
    return AUTH_URL + "?" + urlencode({
        "client_id": cid,
        "redirect_uri": redirect,
        "response_type": "code",
        "scope": SCOPES,
        "access_type": "offline",   # we need a refresh token
        "prompt": "consent",        # force a refresh token even on re-consent
        "include_granted_scopes": "true",
        "state": sign_state(stake_id, subject),
    })


def exchange_code(code: str) -> dict:
    """Authorization code -> {refresh_token, access_token, email}."""
    cid, csec, redirect = _cfg()
    r = requests.post(TOKEN_URL, data={
        "code": code, "client_id": cid, "client_secret": csec,
        "redirect_uri": redirect, "grant_type": "authorization_code"}, timeout=30)
    if r.status_code != 200:
        logger.warning("google token exchange -> %s", r.status_code)
        raise OAuthError(f"token exchange failed ({r.status_code})")
    t = r.json()
    refresh = t.get("refresh_token")
    if not refresh:
        raise OAuthError("Google returned no refresh token — remove the app at "
                         "myaccount.google.com/permissions and reconnect")
    return {"refresh_token": refresh, "access_token": t.get("access_token"),
            "email": _email_from_id_token(t.get("id_token"))}


def _email_from_id_token(id_token: str | None) -> str | None:
    if not id_token:
        return None
    try:
        return json.loads(_unb64(id_token.split(".")[1])).get("email")
    except Exception:  # noqa: BLE001
        return None


def refresh_access_token(refresh_token: str) -> str:
    """Stored refresh token -> a fresh access token (for a Drive/Sheets call)."""
    cid, csec, _ = _cfg()
    r = requests.post(TOKEN_URL, data={
        "refresh_token": refresh_token, "client_id": cid, "client_secret": csec,
        "grant_type": "refresh_token"}, timeout=30)
    if r.status_code != 200:
        raise OAuthError(f"token refresh failed ({r.status_code}) — the leader must reconnect Drive")
    return r.json()["access_token"]


# --- at-rest storage (envelope-encrypt the refresh token) ------------------

def encrypt_refresh(refresh_token: str) -> str:
    return _encrypt_envelope(refresh_token.encode())


def decrypt_refresh(blob: str) -> str:
    return _decrypt_envelope(blob).decode()


def access_token_for(encrypted_refresh: str) -> str:
    """Decrypt a stored refresh token and exchange it for a fresh access token (sync side)."""
    return refresh_access_token(decrypt_refresh(encrypted_refresh))
