"""
Store a stake's own (encrypted) Resend API key so its email uses its own quota.
See docs/CUSTOM_API_KEYS.md.

  python -m backend.set_stake_key --stake <unit_number> --resend-key re_xxx \
      --from "Stake Name <noreply@yourdomain.org>"
"""

from __future__ import annotations

import argparse
import sys

from cryptography.fernet import Fernet

from backend import db
from lcr_client.token_store import _load_key


def main() -> int:
    ap = argparse.ArgumentParser(description="Set a stake's own Resend API key")
    ap.add_argument("--stake", type=int, required=True, help="stake unit number")
    ap.add_argument("--resend-key", required=True)
    ap.add_argument("--from", dest="from_email", default=None, help="From: header (verified domain)")
    args = ap.parse_args()

    enc = Fernet(_load_key()).encrypt(args.resend_key.encode("utf-8")).decode("ascii")
    conn = db.connect()
    try:
        with conn.cursor() as cur:
            cur.execute("select id from stakes where unit_number=%s", (args.stake,))
            row = cur.fetchone()
            if not row:
                print(f"[!] stake {args.stake} not found (onboard it first)")
                return 1
            cur.execute("""insert into stake_settings (stake_id, resend_api_key_enc, email_from, updated_at)
                           values (%s,%s,%s, now())
                           on conflict (stake_id) do update set
                             resend_api_key_enc=excluded.resend_api_key_enc,
                             email_from=coalesce(excluded.email_from, stake_settings.email_from),
                             updated_at=now()""", (row[0], enc, args.from_email))
        conn.commit()
    finally:
        conn.close()
    print(f"[+] stored Resend key for stake {args.stake} (encrypted); from={args.from_email or '(shared)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
