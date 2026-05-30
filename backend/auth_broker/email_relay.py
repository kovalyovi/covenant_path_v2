"""
Email-OTP relay — sign in via the broker when the browser can't reach Supabase directly.

Some networks (e.g. the operator's father in Russia) can reach our broker but have trouble with the
browser → supabase.co auth dance (CORS / filtering). This relays both legs server-side:

    POST /auth/email/start  {email}        -> Supabase /auth/v1/otp   (sends the 6-digit code email)
    POST /auth/email/verify {email, code}  -> Supabase /auth/v1/verify -> {access_token, refresh_token}

The app then calls supabase.auth.setSession(refresh_token) to establish an RLS-scoped session.
Ownership is still proven the normal way (the user must enter the code emailed to them) — the broker
only carries the requests, it does not bypass verification. Uses the public anon key as `apikey`
(falls back to the service-role key if SUPABASE_ANON_KEY isn't set on the broker).
"""

from __future__ import annotations

import os
import time

import requests

from lcr_client.logging_setup import get_logger

logger = get_logger()
_TIMEOUT = 30

# Defense-in-depth against using the relay to email-bomb a victim: a per-email cooldown on top of
# Supabase's own OTP rate limit. In-memory is fine — the broker runs single-instance.
_COOLDOWN_SECONDS = 30
_last_start: dict[str, float] = {}


class RelayError(RuntimeError):
    pass


def _cfg() -> tuple[str, str]:
    url = os.environ.get("SUPABASE_URL")
    # auth endpoints want the public anon key as apikey; service role also works as a fallback.
    key = os.environ.get("SUPABASE_ANON_KEY") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise RelayError("SUPABASE_URL / SUPABASE_ANON_KEY not set on the broker")
    return url.rstrip("/"), key


def _headers(key: str) -> dict:
    return {"apikey": key, "Content-Type": "application/json"}


def start_email_login(email: str) -> dict:
    """Ask Supabase to email a one-time code to [email]. create_user so first-time leaders work."""
    email = (email or "").strip().lower()
    if "@" not in email or len(email) > 254:
        raise RelayError("a valid email is required")
    now = time.time()
    last = _last_start.get(email, 0)
    if now - last < _COOLDOWN_SECONDS:
        raise RelayError("a code was just sent — please wait a moment before requesting another")
    _last_start[email] = now
    url, key = _cfg()
    r = requests.post(f"{url}/auth/v1/otp", headers=_headers(key),
                      json={"email": email, "create_user": True}, timeout=_TIMEOUT)
    if r.status_code not in (200, 201):
        # PII-safe: log the status only, never the email or Supabase's (possibly email-bearing) body.
        logger.warning("relay otp start -> %s", r.status_code)
        raise RelayError(f"could not send the code ({r.status_code})")
    logger.info("relay: sent email code to a user")
    return {"ok": True}


def verify_email_login(email: str, code: str) -> dict:
    """Verify the emailed code server-side and return the Supabase session tokens for the app to
    adopt via setSession. The code proves ownership exactly as a direct verify would."""
    email = (email or "").strip().lower()
    code = (code or "").strip()
    if "@" not in email or not code:
        raise RelayError("email and code are required")
    url, key = _cfg()
    r = requests.post(f"{url}/auth/v1/verify", headers=_headers(key),
                      json={"type": "email", "email": email, "token": code}, timeout=_TIMEOUT)
    if r.status_code != 200:
        logger.info("relay verify -> %s", r.status_code)  # 400/401 = wrong/expired code (expected)
        raise RelayError("that code didn't match or has expired — request a new one")
    data = r.json()
    access, refresh = data.get("access_token"), data.get("refresh_token")
    if not access or not refresh:
        raise RelayError("verification succeeded but no session was returned")
    logger.info("relay: minted a session for a user")
    return {"access_token": access, "refresh_token": refresh,
            "expires_in": data.get("expires_in"), "token_type": data.get("token_type", "bearer")}
