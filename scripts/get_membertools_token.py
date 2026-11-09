#!/usr/bin/env python3
"""Print a stake's stored Member Tools refresh token (no login).

Same source the daily sync uses: the Supabase-persisted 45-day token
(migration 0049) first, the local file store as a dev fallback — the same
lookup as ``scripts.daily_sync._membertools_token``. Used by the
pull-stake-data CI workflow so ``scripts/pull_stake_data.py`` can renew its
bearer from ``MEMBERTOOLS_REFRESH_TOKEN`` without a headless Okta login
(which fails HTTP 428 at the IDX identify step).

Usage:
    python scripts/get_membertools_token.py [--stake 503991]

Prints ONLY the refresh token to stdout; all diagnostics go to stderr.
Exit 0 with a token, 1 when no token is stored (the caller then falls back
to the Okta login instead of failing).

The token is a secret: callers must mask it before it can reach any log
(e.g. ``echo "::add-mask::$TOKEN"`` in GitHub Actions) and never echo it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root on path

DEFAULT_STAKE_UNIT = 503991


def get_token(stake_unit: int) -> str | None:
    """Stored Member Tools refresh token for a stake, or None.

    Supabase first (persists across CI), else the local file store.
    A DB-read failure is logged to stderr and falls through to the file
    store; it never raises here — the caller decides the fallback.
    """
    db_errored = False
    try:
        from backend import credentials, db

        conn = db.connect()
        try:
            sid = credentials.stake_id_for_unit(conn, stake_unit)
            tok = credentials.get_membertools_refresh(conn, sid) if sid else None
            if tok and tok.get("refresh_token"):
                return tok["refresh_token"]
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001 — DB hiccup: try the file store
        db_errored = True
        print(f"[!] Member Tools token DB read failed for stake {stake_unit}: {exc}",
              file=sys.stderr)
    try:
        from lcr_client import token_store

        ft = token_store.get_membertools_token(stake_unit) or {}
        if ft.get("refresh_token"):
            return ft["refresh_token"]
    except Exception as exc:  # noqa: BLE001 — file store unreadable
        print(f"[!] Member Tools token file-store read failed: {exc}", file=sys.stderr)
    if db_errored:
        print("[!] token store unreadable (DB error, file store empty)",
              file=sys.stderr)
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Print a stake's stored Member Tools refresh token.")
    parser.add_argument("--stake", type=int, default=DEFAULT_STAKE_UNIT,
                        help="LCR stake unit number (default: %(default)s)")
    args = parser.parse_args(argv)

    token = get_token(args.stake)
    if not token:
        print(f"[!] no stored Member Tools refresh token for stake {args.stake}",
              file=sys.stderr)
        return 1
    # ONLY the token goes to stdout — nothing else, so callers can capture it.
    print(token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
