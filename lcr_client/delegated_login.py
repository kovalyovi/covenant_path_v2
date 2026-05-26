"""
Delegated authorization: let a higher-access leader authorize the script on their
behalf — WITHOUT ever sharing a password — and run long-term under that access.

Design (see PROGRESS.md "Delegated access"):
  authorize()  Opens a real browser to LCR's official login. The leader signs in on
               Okta's OWN hosted page (their password only ever touches Okta — never
               our code). Once authenticated, we capture the session cookies (incl. the
               long-lived Okta session cookie `idx`), confirm the leader's calling via
               the access matrix, record explicit consent + an expiry, and persist it
               ENCRYPTED, scoped to the stake (lcr_client/token_store.py).

  mint_session()  Unattended: load the stored session, SSO through /api/auth/login to
               (re)mint fresh LCR cookies (works while the Okta session is alive), then
               RE-VERIFY the principal still holds the granting calling. If the calling
               changed (released) the grant is auto-revoked. Expiry and the revoke
               kill-switch are enforced. The minted session is written to storage_state.json
               so the whole pipeline runs as the authorizing leader.

The stored secret is the leader's session (Okta + LCR cookies), encrypted at rest.
It is never logged. A grant is revocable (revoke / kill-switch) and expires; past
expiry or after a calling change, the leader simply re-authorizes via the link.

CLI:
  python -m lcr_client.delegated_login authorize [--stake N] [--headless] [--days 30]
  python -m lcr_client.delegated_login mint --stake N
  python -m lcr_client.delegated_login status
  python -m lcr_client.delegated_login revoke --stake N [--reason "..."]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from lcr_client import okta_login, token_store
from lcr_client.access import covenant_path_access
from lcr_client.logging_setup import get_logger

logger = get_logger()
LCR = "https://lcr.churchofjesuschrist.org"
DEFAULT_STORAGE_STATE = okta_login.DEFAULT_STORAGE_STATE
DEFAULT_LIFETIME_DAYS = 30
_AUTHED = (
    lambda u: "lcr.churchofjesuschrist.org" in u
    and "sign-in" not in u
    and "id.churchofjesuschrist.org" not in u
)


class DelegationError(RuntimeError):
    pass


# --- browser capture (the only browser use; password goes only to Okta) ------

def _capture_session(headless: bool, login_timeout_s: int, auto_login_for_test: bool) -> list[dict]:
    """Open LCR, let the leader log in on Okta's hosted page, capture cookies."""
    from playwright.sync_api import sync_playwright

    cookies: list[dict] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        ctx = browser.new_context()
        page = ctx.new_page()
        page.goto(f"{LCR}/", wait_until="domcontentloaded", timeout=60000)

        if auto_login_for_test:
            # TEST ONLY: simulate the leader using env creds (still typed into the
            # rendered Okta page, not handled by us beyond the test harness).
            import os

            from dotenv import load_dotenv
            sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
            from lcr_crawler import attempt_login

            load_dotenv()
            attempt_login(page, os.getenv("LCR_LOGIN"), os.getenv("LCR_PASSWORD"))
        else:
            print("\n" + "=" * 68)
            print("A browser window opened. Please have the AUTHORIZING LEADER sign in")
            print("to LCR (their password is entered only on the Church's login page —")
            print("it is never seen or stored by this script). Waiting for sign-in...")
            print("=" * 68)

        try:
            page.wait_for_url(_AUTHED, timeout=login_timeout_s * 1000)
            page.wait_for_load_state("networkidle", timeout=20000)
        except Exception as exc:  # noqa: BLE001
            browser.close()
            raise DelegationError(f"login not completed within {login_timeout_s}s: {exc}") from exc

        state = ctx.storage_state()
        cookies = [c for c in state.get("cookies", [])
                   if "churchofjesuschrist.org" in (c.get("domain") or "")]
        browser.close()
    if not cookies:
        raise DelegationError("no churchofjesuschrist.org cookies captured")
    return cookies


def _client_from_cookies(cookies: list[dict]):
    """Build an LcrClient backed by an in-memory session seeded with cookies."""
    from lcr_client import LcrClient
    from lcr_client.auth import LcrSession

    session = LcrSession.__new__(LcrSession)  # bypass file-based __init__
    session.lang = "eng"
    session.auto_login = False
    session.storage_state_path = Path(DEFAULT_STORAGE_STATE)
    session.session = okta_login.session_from_cookies(cookies)
    session.session.headers.update({"Accept": "application/json, text/plain, */*"})
    return LcrClient(session=session)


def _stake_of(positions: list[dict], override: int | None) -> tuple[int, str]:
    if override:
        return override, next((p["unit"] for p in positions if p["unit_number"] == override),
                              f"unit {override}")
    for p in positions:
        if p.get("unit_number") and "stake" in (p.get("name", "").lower()):
            return p["unit_number"], p.get("unit") or f"unit {p['unit_number']}"
    if positions and positions[0].get("unit_number"):
        return positions[0]["unit_number"], positions[0].get("unit") or "?"
    raise DelegationError("could not determine the stake unit from the leader's positions")


# --- public API --------------------------------------------------------------

def authorize(
    stake_unit: int | None = None,
    headless: bool = False,
    max_lifetime_days: int = DEFAULT_LIFETIME_DAYS,
    login_timeout_s: int = 180,
    auto_login_for_test: bool = False,
    require_consent: bool = True,
) -> dict:
    """Capture a leader's session via hosted login and store an encrypted grant."""
    cookies = _capture_session(headless, login_timeout_s, auto_login_for_test)
    client = _client_from_cookies(cookies)

    me = okta_login.verify_session(client.session.session)
    access = covenant_path_access(client)
    positions = access["runner_positions"]
    role_ids = access["role_ids"]
    unit, stake_name = _stake_of(positions, stake_unit)
    principal = me.get("name") or me.get("preferredName") or me.get("email") or "?"

    if not access["can_pull_all"]:
        missing = ", ".join(m["feature"] for m in access["missing"])
        logger.warning("authorizing leader lacks some covenant-path features: %s", missing)
        print(f"[!] Note: this leader's calling is NOT granted: {missing}")

    consent_text = (
        f"I, {principal} ({', '.join(p['name'] for p in positions)}), authorize this "
        f"script to access covenant-path data for {stake_name} ({unit}) on my behalf "
        f"until it expires in {max_lifetime_days} days or I revoke it."
    )
    if require_consent and not auto_login_for_test:
        print("\n" + consent_text)
        if input("Type 'I AGREE' to authorize: ").strip().upper() != "I AGREE":
            raise DelegationError("consent not given — nothing stored")

    now = time.time()
    grant = {
        "stake_unit": unit,
        "stake_name": stake_name,
        "principal": {"name": principal, "positions": [p["name"] for p in positions]},
        "granting_role_ids": role_ids,
        "can_pull_all_at_grant": access["can_pull_all"],
        "granted_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now)),
        "expires_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now + max_lifetime_days * 86400)),
        "max_lifetime_days": max_lifetime_days,
        "consent": True,
        "consent_text": consent_text,
        "cookies": cookies,            # encrypted at rest by token_store
        "refresh_token": None,         # reserved (cookie-session is the mechanism today)
        "revoked": False,
        "revoked_at": None,
        "audit": [{"ts": grant_ts(now), "event": "granted",
                   "detail": {"principal": principal, "roles": role_ids}}],
    }
    token_store.save_grant(grant)
    print(f"\n[+] Authorized: {principal} for {stake_name} ({unit}); expires {grant['expires_at']}.")
    return token_store._redact(grant)


def grant_ts(epoch: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(epoch))


def mint_session(stake_unit: int, storage_state_path: str | Path = DEFAULT_STORAGE_STATE) -> dict:
    """Re-mint an LCR session from a stored grant, re-verifying the calling. Returns identity."""
    grant = token_store.get_grant(stake_unit)
    if not grant:
        raise DelegationError(f"no delegated grant for stake {stake_unit}")
    if grant.get("revoked"):
        raise DelegationError(f"grant for stake {stake_unit} is revoked ({grant.get('revoked_at')})")
    if time.strftime("%Y-%m-%dT%H:%M:%S") > grant.get("expires_at", ""):
        token_store.append_audit(stake_unit, "expired")
        raise DelegationError(f"grant for stake {stake_unit} expired {grant.get('expires_at')} — re-authorize")

    session = okta_login.session_from_cookies(grant["cookies"])
    try:
        okta_login.establish_lcr_session(session)
        me = okta_login.verify_session(session)
    except Exception as exc:  # noqa: BLE001
        token_store.append_audit(stake_unit, "mint_failed", str(exc))
        raise DelegationError(
            f"could not re-mint session for stake {stake_unit} — the leader's Okta session "
            f"likely expired; ask them to re-authorize. ({exc})"
        ) from exc

    # Re-verify the principal STILL holds a granting calling (auto-revoke on change).
    client = _client_from_cookies(
        [{"name": c.name, "value": c.value, "domain": c.domain, "path": c.path}
         for c in session.cookies]
    )
    access = covenant_path_access(client)
    current = set(access["role_ids"])
    granted = set(grant.get("granting_role_ids") or [])
    if granted and not (current & granted):
        token_store.revoke(stake_unit, reason=f"calling changed: {sorted(granted)} -> {sorted(current)}")
        raise DelegationError(
            f"the authorizing leader's calling changed (was {sorted(granted)}, now {sorted(current)}); "
            "grant auto-revoked. A current leader must re-authorize."
        )

    okta_login.write_storage_state(session, storage_state_path)
    token_store.append_audit(stake_unit, "minted",
                             {"principal": me.get("name"), "roles": sorted(current)})
    logger.info("minted delegated session for stake %s as %s", stake_unit, me.get("name"))
    return {"stake_unit": stake_unit, "principal": me.get("name"),
            "role_ids": sorted(current), "expires_at": grant["expires_at"]}


def revoke(stake_unit: int, reason: str = "manual") -> bool:
    return token_store.revoke(stake_unit, reason)


def status() -> list[dict]:
    return token_store.list_grants()


# --- CLI ---------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Delegated LCR authorization")
    sub = parser.add_subparsers(dest="cmd", required=True)
    pa = sub.add_parser("authorize", help="capture a leader's hosted login and store a grant")
    pa.add_argument("--stake", type=int, default=None)
    pa.add_argument("--headless", action="store_true")
    pa.add_argument("--days", type=int, default=DEFAULT_LIFETIME_DAYS)
    pa.add_argument("--test-login", action="store_true",
                    help="TEST: auto-fill env creds instead of waiting for a manual login")
    pm = sub.add_parser("mint", help="re-mint a session from a stored grant")
    pm.add_argument("--stake", type=int, required=True)
    pr = sub.add_parser("revoke", help="revoke a grant (kill switch)")
    pr.add_argument("--stake", type=int, required=True)
    pr.add_argument("--reason", default="manual")
    sub.add_parser("status", help="list grants (redacted)")
    args = parser.parse_args()

    if args.cmd == "authorize":
        authorize(stake_unit=args.stake, headless=args.headless, max_lifetime_days=args.days,
                  auto_login_for_test=args.test_login, require_consent=not args.test_login)
    elif args.cmd == "mint":
        print(mint_session(args.stake))
    elif args.cmd == "revoke":
        print("revoked" if revoke(args.stake, args.reason) else "no such grant")
    elif args.cmd == "status":
        import json
        print(json.dumps(status(), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
