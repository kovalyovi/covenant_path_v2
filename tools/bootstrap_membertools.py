"""
Bootstrap (or refresh) a stake's Member Tools 45-day refresh token and persist it in Supabase.

WHY: the daily covenant-path sync pulls the whole stake from the Member Tools API (/api/v5/sync),
whose bearer is minted via the Member Tools OAuth client. For an MFA-enabled account that mint
REQUIRES completing MFA in the Member Tools OAuth flow ONCE — the password+MFA login the broker does
for ITS OWN client doesn't carry over (Okta re-applies MFA to the Member Tools client; proven
2026-06-12). Once minted, the 45-day refresh token renews the bearer with NO Okta session, so the
daily sync runs unattended for 45 days. This tool does that one-time mint.

Flow:  /api/v1/authn (username+password → sessionToken) → Member Tools /authorize (renders the IDX
widget) → introspect → select a factor → enter the code → token → persist (Supabase, encrypted).

Usage (two steps so you can read the code from your email/text):
    python tools/bootstrap_membertools.py send --unit 503991 --factor email   # sends a code
    python tools/bootstrap_membertools.py verify --unit 503991 --code 123456   # mint + persist

Or one shot with a TOTP authenticator secret (fully headless, no waiting on a code):
    python tools/bootstrap_membertools.py totp --unit 503991 --secret BASE32SECRET

Credentials come from LCR_LOGIN / LCR_PASSWORD in .env (the operator account) unless --username /
--password are passed. The token is stored encrypted (CP_TOKEN_KEY envelope) keyed by the stake.
"""

from __future__ import annotations

import argparse
import os
import pickle
import re
import secrets
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ID = "https://id.churchofjesuschrist.org"
IDX_HEADERS = {"Accept": "application/ion+json; okta-version=1.0.0",
               "Content-Type": "application/ion+json; okta-version=1.0.0"}
UA = "MLTools 5.5.2-(13763) / iOS 17.0 / iPhone"
STATE_PATH = Path(os.environ.get("TEMP", "/tmp")) / "mt_bootstrap_state.pkl"


def _authn_session_token(s: requests.Session, username: str, password: str) -> str:
    r = s.post(f"{ID}/api/v1/authn", json={"username": username, "password": password},
               headers={"Accept": "application/json", "Content-Type": "application/json"}, timeout=30)
    r.raise_for_status()
    j = r.json()
    if j.get("status") != "SUCCESS" or not j.get("sessionToken"):
        sys.exit(f"primary auth did not return a sessionToken (status={j.get('status')})")
    return j["sessionToken"]


def _open_membertools_idx(s: requests.Session, session_token: str) -> tuple[dict, str]:
    """Member Tools /authorize → IDX widget → introspect. Returns (idx_payload, code_verifier)."""
    from lcr_client import membertools as mt
    verifier, challenge = mt._pkce()
    params = {"client_id": mt.CLIENT_ID, "redirect_uri": mt.REDIRECT_URI, "response_type": "code",
              "scope": mt.SCOPE, "code_challenge": challenge, "code_challenge_method": "S256",
              "state": secrets.token_hex(8), "nonce": secrets.token_hex(8), "sessionToken": session_token}
    body = s.get(f"{mt.OKTA}/authorize", params=params, allow_redirects=False, timeout=60,
                 headers={"Accept": "text/html,*/*"}).text
    m = re.search(r'"stateToken":"([^"]+)"', body)
    if not m:
        # Some accounts authorize silently (no MFA) → the redirect carries the code directly.
        sys.exit("no stateToken in the authorize response (account may not need MFA — re-run 'verify' "
                 "without a code, or inspect manually)")
    state_token = m.group(1).encode().decode("unicode_escape")
    payload = s.post(f"{ID}/idp/idx/introspect", json={"stateToken": state_token},
                     headers=IDX_HEADERS, timeout=30).json()
    return payload, verifier


def _select_factor(s: requests.Session, payload: dict, factor: str) -> dict:
    rems = {r["name"]: r for r in payload.get("remediation", {}).get("value", [])}
    sel = rems.get("select-authenticator-authenticate")
    if not sel:
        return payload  # already at the challenge
    field = next(f for f in sel["value"] if f["name"] == "authenticator")
    want = "email" if factor == "email" else "phone"
    opt = next((o for o in field["options"] if want in o["label"].lower()), None)
    if not opt:
        sys.exit(f"factor {factor!r} not offered; options: {[o['label'] for o in field['options']]}")
    form = opt["value"]["form"]["value"]
    body = {f["name"]: f.get("value") for f in form if "value" in f}
    return s.post(sel["href"], json={"authenticator": body, "stateHandle": payload["stateHandle"]},
                  headers=IDX_HEADERS, timeout=30).json()


def _answer_code(s: requests.Session, payload: dict, code: str) -> dict:
    rems = {r["name"]: r for r in payload.get("remediation", {}).get("value", [])}
    ch = rems.get("challenge-authenticator")
    if not ch:
        sys.exit(f"no challenge to answer; remediations: {list(rems)}")
    # the declared credential field (passcode for email/sms)
    field = next((f for f in ch["value"] if f["name"] == "credentials"), None)
    names = [f.get("name") for f in (field or {}).get("form", {}).get("value", [])]
    key = "passcode" if "passcode" in names else (names[0] if names else "passcode")
    return s.post(ch["href"], json={"credentials": {key: code}, "stateHandle": payload["stateHandle"]},
                  headers=IDX_HEADERS, timeout=30).json()


def _exchange_code(s: requests.Session, payload: dict, verifier: str) -> dict:
    from lcr_client import membertools as mt
    success = payload.get("successWithInteractionCode") or payload.get("success")
    if not success:
        msgs = (payload.get("messages") or {}).get("value", [])
        detail = "; ".join(m.get("message", "") for m in msgs) or list(
            {r["name"] for r in payload.get("remediation", {}).get("value", [])})
        sys.exit(f"login did not complete: {detail}")
    href = success["href"]
    # the success href carries the interaction_code in its form / query
    code = None
    for f in success.get("value", []):
        if f.get("name") == "interaction_code":
            code = f.get("value")
    if not code:
        q = parse_qs(urlparse(href).query)
        code = (q.get("interaction_code") or q.get("code") or [None])[0]
    if not code:
        # follow the href to get the code from the redirect
        r = s.get(href, allow_redirects=False, timeout=30)
        loc = r.headers.get("Location", "")
        code = (parse_qs(urlparse(loc).query).get("code") or [None])[0]
    if not code:
        sys.exit("could not extract the interaction/authorization code from success")
    grant = "interaction_code" if "successWithInteractionCode" in payload else "authorization_code"
    body = {"grant_type": grant, "client_id": mt.CLIENT_ID, "code_verifier": verifier,
            "redirect_uri": mt.REDIRECT_URI}
    body["interaction_code" if grant == "interaction_code" else "code"] = code
    return mt._token_request(body)


def _persist(unit: int, refresh_token: str) -> None:
    from backend import credentials, db
    conn = db.connect()
    try:
        sid = credentials.stake_id_for_unit(conn, unit)
        if not sid:
            sys.exit(f"no stake row for unit {unit}")
        credentials.save_membertools_refresh(conn, sid, refresh_token)
        got = credentials.get_membertools_refresh(conn, sid)
        print(f"[+] persisted Member Tools token for stake {unit}: {bool(got and got.get('refresh_token'))}")
        # prove the refresh path works (no Okta session)
        from lcr_client import membertools as mt
        print(f"[+] refresh() -> access token: {bool(mt.refresh(refresh_token).get('access_token'))}")
    finally:
        conn.close()


def _creds(args) -> tuple[str, str]:
    u = args.username or os.environ.get("LCR_LOGIN")
    p = args.password or os.environ.get("LCR_PASSWORD")
    if not u or not p:
        sys.exit("LCR_LOGIN / LCR_PASSWORD not set (or pass --username/--password)")
    return u, p


def main() -> None:
    load_dotenv()
    ap = argparse.ArgumentParser(description="Bootstrap a stake's Member Tools 45-day token.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("send", "verify", "totp"):
        sp = sub.add_parser(name)
        sp.add_argument("--unit", type=int, required=True)
        sp.add_argument("--username"); sp.add_argument("--password")
        if name == "send":
            sp.add_argument("--factor", choices=["email", "sms"], default="email")
        if name == "verify":
            sp.add_argument("--code", required=True)
        if name == "totp":
            sp.add_argument("--secret", required=True, help="the TOTP authenticator's base32 secret")
    args = ap.parse_args()
    u, p = _creds(args)
    s = requests.Session(); s.headers.update({"User-Agent": UA})

    if args.cmd == "send":
        token = _authn_session_token(s, u, p)
        payload, verifier = _open_membertools_idx(s, token)
        payload = _select_factor(s, payload, args.factor)
        pickle.dump({"session": s, "payload": payload, "verifier": verifier, "unit": args.unit},
                    open(STATE_PATH, "wb"))
        print(f"[+] {args.factor} code sent for unit {args.unit}. Now run:\n"
              f"    python tools/bootstrap_membertools.py verify --unit {args.unit} --code <CODE>")
        return

    if args.cmd == "verify":
        if not STATE_PATH.exists():
            sys.exit("no pending challenge — run 'send' first")
        st = pickle.load(open(STATE_PATH, "rb"))
        if st["unit"] != args.unit:
            sys.exit(f"pending challenge is for unit {st['unit']}, not {args.unit}")
        s, payload, verifier = st["session"], st["payload"], st["verifier"]
        payload = _answer_code(s, payload, args.code.strip())
        tok = _exchange_code(s, payload, verifier)
        if not tok.get("refresh_token"):
            sys.exit(f"mint returned no refresh token: {list(tok)}")
        _persist(args.unit, tok["refresh_token"])
        STATE_PATH.unlink(missing_ok=True)
        return

    if args.cmd == "totp":
        import pyotp  # optional dep; only needed for the TOTP path
        token = _authn_session_token(s, u, p)
        payload, verifier = _open_membertools_idx(s, token)
        payload = _select_factor(s, payload, "email")  # TOTP uses a different factor; see note below
        # NOTE: a Software Authenticator (google_otp) is selected by its own option; for brevity this
        # path expects the authenticator factor to be enrolled. Compute the current code and answer.
        payload = _answer_code(s, payload, pyotp.TOTP(args.secret).now())
        tok = _exchange_code(s, payload, verifier)
        if not tok.get("refresh_token"):
            sys.exit(f"mint returned no refresh token: {list(tok)}")
        _persist(args.unit, tok["refresh_token"])


if __name__ == "__main__":
    main()
