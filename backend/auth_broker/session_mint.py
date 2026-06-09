"""
Mint a Supabase session for a verified Church identity, via the Supabase Admin API.

The project uses asymmetric JWT signing keys, so we can't forge our own JWTs. Instead:
ensure the auth user exists, then generate a magic-link OTP (admin) and hand the app the
OTP — the app calls supabase.auth.verifyOtp(email, otp) to obtain a real Supabase session.
RLS then scopes that session by the verified email (matched to user_roles).

Needs SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY. The OTP is session-granting — logged as
"minted", never by value.
"""

from __future__ import annotations

import os

import requests

from lcr_client.logging_setup import get_logger

logger = get_logger()
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36")


class MintError(RuntimeError):
    pass


def _cfg() -> tuple[str, str]:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise MintError("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not set "
                        "(service_role from Supabase -> Settings -> API)")
    return url.rstrip("/"), key


def _headers(key: str) -> dict:
    return {"apikey": key, "Authorization": f"Bearer {key}",
            "Content-Type": "application/json", "User-Agent": _UA}


def mint_otp(email: str) -> dict:
    """Ensure the user exists and return a magic-link OTP for the app to verify."""
    if not email:
        raise MintError("no email on the Church identity — can't mint a session")
    url, key = _cfg()
    h = _headers(key)

    def _link():
        return requests.post(f"{url}/auth/v1/admin/generate_link",
                             json={"type": "magiclink", "email": email}, headers=h, timeout=30)

    # Cheap path first: everyone but a brand-new user gets their OTP in ONE round-trip; the
    # idempotent create-user call only runs when generate_link says the user doesn't exist.
    r = _link()
    if r.status_code in (400, 404, 422):
        c = requests.post(f"{url}/auth/v1/admin/users",
                          json={"email": email, "email_confirm": True}, headers=h, timeout=30)
        if c.status_code not in (200, 201) and "already" not in c.text.lower():
            logger.warning("admin create_user %s -> %s %s", email, c.status_code, c.text[:160])
        r = _link()
    if r.status_code not in (200, 201):
        raise MintError(f"generate_link failed: {r.status_code} {r.text[:160]}")
    data = r.json()
    otp = data.get("email_otp") or data.get("properties", {}).get("email_otp")
    if not otp:
        raise MintError("generate_link returned no email_otp")
    logger.info("minted Supabase session OTP for %s", email)
    return {"email": email, "otp": otp}
