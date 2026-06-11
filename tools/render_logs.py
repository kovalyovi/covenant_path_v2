"""
Pull broker logs from Render's API — no more dashboard copy-paste for incident digs.

Setup (one-time): Render Dashboard -> Account Settings -> API Keys -> create, then put
RENDER_API_KEY=rnd_... in .env (gitignored). The service is auto-discovered by name;
pin it with RENDER_SERVICE_ID=srv-... if the account ever hosts more than one service.

Usage:
  python tools/render_logs.py --since 2h --text auth        # login-flow lines, last 2h
  python tools/render_logs.py --start 2026-06-11T12:20:00Z --end 2026-06-11T12:30:00Z
  python tools/render_logs.py --since 30m --text "req 3cb989c0"

Times are UTC. Render keeps logs only for days — pull evidence promptly after an incident.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv

API = "https://api.render.com/v1"


def _headers() -> dict:
    key = os.environ.get("RENDER_API_KEY", "")
    if not key:
        sys.exit("RENDER_API_KEY missing — create one at Render Dashboard -> Account Settings "
                 "-> API Keys and add it to .env")
    return {"Authorization": f"Bearer {key}", "Accept": "application/json"}


def _get(path: str, params: dict) -> dict | list:
    resp = requests.get(f"{API}{path}", headers=_headers(), params=params, timeout=30)
    if resp.status_code != 200:
        sys.exit(f"Render API {path} -> {resp.status_code}: {resp.text[:500]}")
    return resp.json()


def find_service(name_hint: str) -> tuple[str, str]:
    """Return (service_id, owner_id). RENDER_SERVICE_ID pins the service; otherwise match by name."""
    pinned = os.environ.get("RENDER_SERVICE_ID", "")
    rows = _get("/services", {"limit": 50})
    services = [r.get("service", r) for r in rows] if isinstance(rows, list) else []
    if not services:
        sys.exit("no services visible to this API key")
    for svc in services:
        if pinned and svc.get("id") == pinned:
            return svc["id"], svc.get("ownerId", "")
        if not pinned and name_hint.lower() in (svc.get("name") or "").lower():
            return svc["id"], svc.get("ownerId", "")
    if pinned:
        sys.exit(f"RENDER_SERVICE_ID={pinned} not found; visible: "
                 + ", ".join(f'{s.get("name")}={s.get("id")}' for s in services))
    if len(services) == 1:
        return services[0]["id"], services[0].get("ownerId", "")
    sys.exit(f"no service name matches {name_hint!r}; visible: "
             + ", ".join(f'{s.get("name")}={s.get("id")}' for s in services))


def _parse_since(s: str) -> datetime:
    m = re.fullmatch(r"(\d+)([mhd])", s.strip())
    if not m:
        sys.exit(f"--since must look like 30m / 2h / 1d (got {s!r})")
    n, unit = int(m.group(1)), m.group(2)
    delta = {"m": timedelta(minutes=n), "h": timedelta(hours=n), "d": timedelta(days=n)}[unit]
    return datetime.now(timezone.utc) - delta


def _parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def fetch_logs(service_id: str, owner_id: str, start: datetime, end: datetime,
               text: str | None, max_pages: int) -> list[dict]:
    """Page backwards from `end` until `start` is covered (the API caps each page at 100 lines)."""
    out: list[dict] = []
    end_cursor = end
    for _ in range(max_pages):
        params: dict = {
            "ownerId": owner_id,
            "resource": service_id,
            "startTime": start.isoformat().replace("+00:00", "Z"),
            "endTime": end_cursor.isoformat().replace("+00:00", "Z"),
            "limit": 100,
            "direction": "backward",
        }
        if text:
            params["text"] = text
        data = _get("/logs", params)
        logs = data.get("logs", []) if isinstance(data, dict) else data
        out.extend(logs)
        if not (isinstance(data, dict) and data.get("hasMore")):
            break
        nxt = data.get("nextEndTime")
        if not nxt:
            break
        end_cursor = _parse_iso(nxt)
    return out


def main() -> None:
    load_dotenv()
    ap = argparse.ArgumentParser(description="Fetch Render service logs (UTC).")
    ap.add_argument("--since", help="relative window, e.g. 30m / 2h / 1d (default 1h)")
    ap.add_argument("--start", help="ISO start time, e.g. 2026-06-11T12:20:00Z")
    ap.add_argument("--end", help="ISO end time (default now)")
    ap.add_argument("--text", help="server-side text filter, e.g. 'auth' or a request id")
    ap.add_argument("--grep", help="extra client-side regex filter on the message")
    ap.add_argument("--service", default="broker", help="service-name substring (default: broker)")
    ap.add_argument("--max-pages", type=int, default=20, help="pagination cap (100 lines/page)")
    args = ap.parse_args()

    end = _parse_iso(args.end) if args.end else datetime.now(timezone.utc)
    start = _parse_iso(args.start) if args.start else _parse_since(args.since or "1h")

    service_id, owner_id = find_service(args.service)
    logs = fetch_logs(service_id, owner_id, start, end, args.text, args.max_pages)
    pat = re.compile(args.grep) if args.grep else None
    shown = 0
    for entry in sorted(logs, key=lambda e: e.get("timestamp", "")):
        msg = entry.get("message", "")
        if pat and not pat.search(msg):
            continue
        print(f'{entry.get("timestamp", "?")} {msg}')
        shown += 1
    print(f"-- {shown} lines ({service_id}, {start:%Y-%m-%d %H:%M}Z .. {end:%H:%M}Z)",
          file=sys.stderr)


if __name__ == "__main__":
    main()
