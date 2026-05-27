"""
Onboard a stake to the platform — the productized "Connect LCR" flow (CLI/desktop; a
Flutter WebView wrapper is future work). Captures a leader's LCR session (their password
only touches Okta), then in Supabase: registers the stake + units, stores the encrypted
per-stake credential (so the daily job syncs it unattended), and provisions access roles
from callings.

  python scripts/onboard.py --self      # onboard THIS account's stake (headless okta_login)
  python scripts/onboard.py --capture   # headed browser — a stake leader signs in

After onboarding, the daily multi-stake job (scripts/daily_sync.py, delegated mode) will
sync this stake automatically.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lcr_client.logging_setup import get_logger  # noqa: E402

logger = get_logger()


def _cookies_self() -> list[dict]:
    from lcr_client import okta_login
    okta_login.login()  # refresh storage_state headlessly
    state = json.loads(Path(okta_login.DEFAULT_STORAGE_STATE).read_text(encoding="utf-8"))
    return state["cookies"]


def _cookies_capture() -> list[dict]:
    from lcr_client import delegated_login
    return delegated_login._capture_session(headless=False, login_timeout_s=240,
                                             auto_login_for_test=False)


def onboard(cookies: list[dict], conn) -> dict:
    from lcr_client import okta_login
    from lcr_client.access import covenant_path_access
    from lcr_client.delegated_login import _client_from_cookies
    from backend import credentials, db, roles

    client = _client_from_cookies(cookies)
    me = okta_login.verify_session(client.session.session)
    access = covenant_path_access(client)
    ctx = client.user_context()

    stake_id = db.upsert_stake(conn, ctx.unit_number, ctx.unit_name)
    unit_id_by_name: dict[str, str] = {}
    for u in ctx.child_units:
        if u.unit_number:
            uid = db.upsert_unit(conn, stake_id, u.unit_number, u.name, u.type)
            if u.name:
                unit_id_by_name[u.name] = uid

    credentials.save_credential(conn, stake_id, {
        "cookies": cookies,
        "principal": {"name": me.get("name")},
        "granting_role_ids": access["role_ids"],
    })
    role_summary = roles.provision_roles(conn, client, stake_id, unit_id_by_name)
    return {"stake": ctx.unit_name, "stake_unit": ctx.unit_number, "principal": me.get("name"),
            "units": len(unit_id_by_name), "roles": role_summary,
            "can_pull_all": access["can_pull_all"]}


def main() -> int:
    ap = argparse.ArgumentParser(description="Onboard a stake (Connect LCR)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--self", dest="self_mode", action="store_true",
                   help="onboard this account's stake (headless okta_login)")
    g.add_argument("--capture", action="store_true",
                   help="open a browser for a stake leader to sign in")
    args = ap.parse_args()

    from backend import db
    cookies = _cookies_capture() if args.capture else _cookies_self()
    conn = db.connect()
    try:
        s = onboard(cookies, conn)
    finally:
        conn.close()
    print(f"[+] onboarded {s['stake']} ({s['stake_unit']}) as {s['principal']}: "
          f"{s['units']} units, roles={s['roles']}, full-access={s['can_pull_all']}")
    print("    -> the daily delegated sync will now include this stake.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
