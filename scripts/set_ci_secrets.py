"""
Push GitHub Actions secrets for the daily sync, reading values from .env (and the
Google service-account file). Values are passed to `gh secret set` via stdin, so they
never appear on the command line or in logs.

  python scripts/set_ci_secrets.py            # sets all configured secrets

Requires: gh authenticated (gh auth status). Re-runnable (idempotent).
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _repo_from_git_remote() -> str | None:
    """owner/repo from the origin remote, so a fork/rename needs no code edit."""
    try:
        url = subprocess.run(["git", "-C", str(REPO_ROOT), "remote", "get-url", "origin"],
                             capture_output=True, text=True, check=True).stdout.strip()
    except Exception:  # noqa: BLE001 — best-effort; fall back to env/default
        return None
    m = re.search(r"github\.com[:/]+([^/]+/[^/]+?)(?:\.git)?$", url)
    return m.group(1) if m else None


REPO = os.environ.get("GITHUB_REPO") or _repo_from_git_remote() or "kovalyovi/covenant_path_v2"
TEST_SPREADSHEET_ID = os.environ.get(
    "TEST_SPREADSHEET_ID", "1JD9EC_SafClaY8cOcRzi5ZI4fUnjOxa-xXJA0lxgJaA")


def _gh() -> str:
    for c in (os.environ.get("GH_PATH"), "gh", r"C:/Program Files/GitHub CLI/gh.exe"):
        if c and (c in ("gh",) or Path(c).exists()):
            return c
    raise SystemExit("gh CLI not found; set GH_PATH")


def _set(gh: str, name: str, value: str) -> None:
    if not value:
        print(f"  - skip {name} (not set)")
        return
    subprocess.run([gh, "secret", "set", name, "--repo", REPO],
                   input=value, text=True, check=True)
    print(f"  + set {name}")


def main() -> int:
    from cryptography.fernet import Fernet
    from dotenv import load_dotenv
    load_dotenv(REPO_ROOT / ".env")
    gh = _gh()

    # ensure a stable CP_TOKEN_KEY in .env (so local + CI decrypt the same grants)
    if not os.getenv("CP_TOKEN_KEY"):
        key = Fernet.generate_key().decode()
        with (REPO_ROOT / ".env").open("a", encoding="utf-8") as fh:
            fh.write(f'\nCP_TOKEN_KEY="{key}"\n')
        os.environ["CP_TOKEN_KEY"] = key
        print("  (generated CP_TOKEN_KEY into .env)")

    env_secrets = ["LCR_LOGIN", "LCR_PASSWORD", "CP_TOKEN_KEY",
                   "SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_DB_URL"]
    print(f"setting secrets on {REPO}:")
    for name in env_secrets:
        _set(gh, name, os.getenv(name, ""))

    _set(gh, "SPREADSHEET_ID", os.getenv("SPREADSHEET_ID", TEST_SPREADSHEET_ID))

    sa_path = os.getenv("SHEETS_SERVICE_ACCOUNT") or "sheets_sync/service_account.json"
    if sa_path and Path(sa_path).exists():
        _set(gh, "GOOGLE_SERVICE_ACCOUNT_JSON", Path(sa_path).read_text(encoding="utf-8"))
    else:
        print("  - skip GOOGLE_SERVICE_ACCOUNT_JSON (no service_account.json found)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
