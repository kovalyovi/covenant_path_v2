"""
Create the private GitHub repo and push — using a token from .env (GITHUB_TOKEN),
so the token never appears on the command line or in logs.

Setup:
  1. Create a token at github.com → Settings → Developer settings:
       - Classic token with the `repo` scope (simplest), OR
       - Fine-grained token with Administration: Read/Write (create repo) +
         Contents: Read/Write (push).
  2. Add to .env (gitignored):   GITHUB_TOKEN="ghp_..."
  3. Run:   python scripts/github_setup.py

Idempotent: if the repo already exists it just adds the remote and pushes.
The remote `origin` is set to the clean https URL (no token); auth is passed to the
single push via an in-memory header.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = "covenant_path_v2"
REPO_ROOT = Path(__file__).resolve().parent.parent


def _api(method: str, url: str, token: str, data: dict | None = None):
    req = urllib.request.Request(
        url, data=json.dumps(data).encode() if data else None, method=method,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                 "User-Agent": "covenant-path-setup"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)


def _git(*args, **kw):
    return subprocess.run(["git", *args], cwd=str(REPO_ROOT), check=kw.get("check", True),
                          capture_output=kw.get("capture", False), text=True)


def main() -> int:
    from dotenv import load_dotenv
    load_dotenv(REPO_ROOT / ".env")
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        print("[!] Set GITHUB_TOKEN in .env (classic `repo` scope, or fine-grained "
              "Administration+Contents Read/Write).")
        return 1

    status, me = _api("GET", "https://api.github.com/user", token)
    if status != 200:
        print(f"[!] token check failed ({status}): {me.get('message')}")
        return 1
    user = me["login"]
    print(f"[*] authenticated as {user}")

    status, resp = _api("POST", "https://api.github.com/user/repos", token,
                        {"name": REPO, "private": True,
                         "description": "LCR covenant-path sync platform (v2)"})
    if status == 201:
        print(f"[+] created private repo {resp['full_name']}")
    elif status == 422:
        print(f"[*] repo {user}/{REPO} already exists — continuing")
    else:
        print(f"[!] create failed ({status}): {resp.get('message')}")
        return 1

    clean_url = f"https://github.com/{user}/{REPO}.git"
    _git("remote", "remove", "origin", check=False)
    _git("remote", "add", "origin", clean_url)
    # auth passed only to this push via an in-memory header; origin URL stays token-free
    header = "Authorization: Basic " + base64.b64encode(f"{user}:{token}".encode()).decode()
    _git("-c", f"http.extraheader={header}", "push", "-u", "origin", "main")
    print(f"[+] pushed main -> {clean_url} (private)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
