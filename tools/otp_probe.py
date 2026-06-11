"""
Probe: does the REAL Church Okta offer passwordless (emailed-code) PRIMARY sign-in?

Runs the same identify-only leg the broker's otp_start uses — interact -> introspect ->
identify with ONLY the username (no password, no code is requested or consumed) — and prints
which authenticators Okta offers as the NEXT step. This is exactly what visiting the sign-in
page and typing a username does; nothing is authenticated and no factor is selected.

  - If the menu lists an Email factor  -> passwordless is ENABLED for this account; the app's
    "Email code" enrollment option will work in production.
  - If only Password is offered (or a password challenge comes straight back) -> passwordless
    is NOT enabled; the app shows the honest "use your password" message.

Usage:  python tools/otp_probe.py [username]     (defaults to LCR_LOGIN from .env)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402


def main() -> int:
    load_dotenv()
    import os

    if os.environ.get("CP_TEST_MODE"):
        print("CP_TEST_MODE is set — this would probe the MOCK, not the real Okta. Unset it.")
        return 2
    identifier = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("LCR_LOGIN", "")).strip()
    if not identifier:
        print("No identifier: pass one as an argument or set LCR_LOGIN in .env")
        return 2

    from lcr_client.okta_login import new_session
    from backend.auth_broker import okta_flow

    session = new_session()
    payload, _ = okta_flow._drive_to_identify(session, identifier, "probe")

    summary = okta_flow._idx_summary(payload)
    print(f"post-identify remediations: {summary['remediations']}")
    print(f"authenticator types offered: {summary['factor_types']}")

    rems = okta_flow._remediations(payload)
    sel = rems.get("select-authenticator-authenticate")
    factors = okta_flow._factors(sel, okta_flow._authenticator_types(payload)) if sel else []
    if factors:
        print("primary factor menu (password excluded by design):")
        for f in factors:
            print(f"  - {f['label']}  (type={f.get('type') or '?'}, method={f.get('method') or '?'})")
    email = next((f for f in factors if f.get("type") == "okta_email"), None)
    if email is not None:
        print("\nVERDICT: PASSWORDLESS AVAILABLE — Okta offers an Email factor before any "
              "password. The app's 'Email code' enrollment will work for this account.")
        return 0
    print("\nVERDICT: NOT AVAILABLE — Okta requires the password first for this account. "
          "The app's 'Email code' option will show its honest 'use your password' message.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
