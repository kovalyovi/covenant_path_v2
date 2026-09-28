#!/usr/bin/env python3
"""Fetch a fresh stake_data.json via the pull-stake-data.yml GitHub workflow.

The roster pull needs Church credentials, which live as LCR_LOGIN /
LCR_PASSWORD *GitHub secrets* — never on this machine. So the pull itself
runs in CI; this script just triggers it, waits, and downloads the artifact
into tools/output/stake_data.json, where scripts/stake.py and other local
tooling (e.g. the HC -> Callings List sync) pick it up automatically.

Usage:
    python scripts/fetch_stake_data.py [--refresh] [--max-age-days 7]

  --refresh           pull even if the local file is still fresh
  --max-age-days N    treat a local file older than N days as stale (default 7)

Requires: gh authenticated (gh auth status).
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT = REPO_ROOT / "tools" / "output" / "stake_data.json"
WORKFLOW = "pull-stake-data.yml"
ARTIFACT = "stake-data"
WAIT_TIMEOUT_S = 15 * 60
POLL_S = 15


def sh(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(list(args), capture_output=True, text=True, timeout=120)


def gh_ok() -> bool:
    return sh("gh", "auth", "status").returncode == 0


def repo_slug() -> str:
    p = sh("git", "-C", str(REPO_ROOT), "remote", "get-url", "origin")
    url = p.stdout.strip().removesuffix(".git")
    # https://github.com/owner/repo  or  git@github.com:owner/repo
    if "github.com" in url:
        slug = url.split("github.com", 1)[1].lstrip("/: ")
        return slug
    raise RuntimeError(f"cannot parse owner/repo from remote: {url!r}")


def local_age_days() -> float | None:
    """Age of the local roster in days, or None if missing/unusable."""
    try:
        data = json.loads(OUT.read_text(encoding="utf-8"))
        if not isinstance(data.get("members"), list) or not data["members"]:
            return None
    except Exception:  # noqa: BLE001 - missing or corrupt counts as stale
        return None
    mtime = datetime.fromtimestamp(OUT.stat().st_mtime, tz=timezone.utc)
    return (datetime.now(timezone.utc) - mtime).total_seconds() / 86400


def runs(status: str = "") -> list[dict]:
    p = sh("gh", "run", "list", "--repo", repo_slug(), "--workflow", WORKFLOW,
           "--limit", "10", "--json", "databaseId,status,conclusion,createdAt")
    if p.returncode != 0:
        raise RuntimeError(f"gh run list failed: {p.stderr.strip()[:200]}")
    items = json.loads(p.stdout or "[]")
    return [r for r in items if not status or r["status"] == status]


def trigger() -> None:
    # Reuse an already-running pull instead of stacking a second one.
    active = runs()
    active = [r for r in active if r["status"] in ("queued", "in_progress")]
    if active:
        print(f"[*] pull already running (run {active[0]['databaseId']}); waiting on it")
        return
    p = sh("gh", "workflow", "run", "--repo", repo_slug(), WORKFLOW)
    if p.returncode != 0:
        raise RuntimeError(f"gh workflow run failed: {p.stderr.strip()[:200]}")
    print("[*] workflow triggered")


def wait_for_run(since_ts: float) -> dict:
    """Wait for the newest run created after since_ts to complete."""
    deadline = time.time() + WAIT_TIMEOUT_S
    target = None
    while time.time() < deadline:
        for r in runs():
            created = datetime.fromisoformat(r["createdAt"].replace("Z", "+00:00")).timestamp()
            if created >= since_ts - 5 and r["status"] in ("queued", "in_progress", "completed"):
                target = r
                break
        if target is None:
            time.sleep(POLL_S)
            continue
        # Refresh this run's status.
        cur = [x for x in runs() if x["databaseId"] == target["databaseId"]]
        if cur and cur[0]["status"] == "completed":
            return cur[0]
        time.sleep(POLL_S)
    raise TimeoutError("timed out waiting for the pull workflow to finish")


def download(run_id: int) -> None:
    tmp = Path(tempfile.mkdtemp(prefix="stake-data-"))
    try:
        p = sh("gh", "run", "download", str(run_id), "--repo", repo_slug(),
               "-n", ARTIFACT, "-D", str(tmp))
        if p.returncode != 0:
            raise RuntimeError(f"gh run download failed: {p.stderr.strip()[:200]}")
        found = next(tmp.rglob("stake_data.json"), None)
        if not found:
            raise RuntimeError(f"artifact {ARTIFACT!r} has no stake_data.json")
        data = json.loads(found.read_text(encoding="utf-8"))
        members = data.get("members") or []
        if not members:
            raise RuntimeError("downloaded stake_data.json has no members")
        OUT.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(found), str(OUT))
        meta = data.get("meta", {})
        print(f"[+] {len(members)} members, {len(data.get('units', []))} units "
              f"-> {OUT} (pulled {meta.get('pulled_at', '?')})")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--max-age-days", type=float, default=7)
    args = ap.parse_args()

    age = local_age_days()
    if not args.refresh and age is not None and age <= args.max_age_days:
        print(f"[*] local roster is {age:.1f}d old (<= {args.max_age_days}g); "
              f"nothing to do -> {OUT}")
        return 0
    if not gh_ok():
        print("[-] gh is not authenticated. Run `gh auth login` once, then retry.",
              file=sys.stderr)
        return 2

    print(f"[*] local roster: {'missing/corrupt' if age is None else f'{age:.1f}d old'}; pulling fresh copy")
    trigger()
    run = wait_for_run(time.time())
    print(f"[*] run {run['databaseId']} {run['status']}/{run.get('conclusion')}")
    if run.get("conclusion") != "success":
        print("[-] pull workflow did not succeed; local file left untouched",
              file=sys.stderr)
        return 1
    download(run["databaseId"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
