"""
One-time network capture for a given LCR page (investigation).

Injects the existing session cookies into a headless browser, opens a page, and
records every XHR/fetch JSON request it makes (method, URL, status, response shape)
so we can discover the runtime APIs that report pages call to load their data
(e.g. the bulk per-unit recommend / ministering reports).

Usage:
  python tools/capture_network.py "<url-or-path>"
"""

import json
import sys
from pathlib import Path
from urllib.parse import urlparse

STATE = Path(__file__).resolve().parent / "output" / "storage_state.json"
OUT = Path(__file__).resolve().parent / "output" / "_network_capture.json"
BASE = "https://lcr.churchofjesuschrist.org"


def shape(body):
    if isinstance(body, dict):
        return {"type": "object", "keys": sorted(body.keys())[:25]}
    if isinstance(body, list):
        first = body[0] if body else None
        return {"type": "array", "len": len(body),
                "item_keys": sorted(first.keys())[:25] if isinstance(first, dict) else None}
    return {"type": type(body).__name__}


def main() -> int:
    from playwright.sync_api import sync_playwright

    url = sys.argv[1] if len(sys.argv) > 1 else "/"
    if url.startswith("/"):
        url = BASE + url
    captured = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(storage_state=str(STATE))
        page = ctx.new_page()

        def on_response(resp):
            req = resp.request
            if req.resource_type not in ("xhr", "fetch"):
                return
            host = urlparse(req.url).hostname or ""
            if "churchofjesuschrist.org" not in host:
                return
            ctype = (resp.headers or {}).get("content-type", "")
            try:
                post = (req.post_data or "")[:200]
            except Exception:
                post = "<binary>"
            entry = {"method": req.method, "url": req.url, "status": resp.status,
                     "ctype": ctype, "post": post}
            if "application/json" in ctype:
                try:
                    entry["shape"] = shape(resp.json())
                except Exception:
                    pass
            captured.append(entry)

        ctx.on("response", on_response)
        print(f"[*] opening {url}")
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        try:
            page.wait_for_load_state("networkidle", timeout=30000)
        except Exception:
            pass
        page.wait_for_timeout(3000)
        browser.close()

    OUT.write_text(json.dumps(captured, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[+] {len(captured)} xhr/fetch calls -> {OUT}\n")
    for e in captured:
        path = urlparse(e["url"]).path
        q = urlparse(e["url"]).query
        sh = e.get("shape", {})
        marker = ""
        if sh.get("type") == "array" and sh.get("len", 0) > 0:
            marker = f"  <- array[{sh['len']}] {sh.get('item_keys')}"
        elif sh.get("type") == "object":
            marker = f"  <- obj {sh.get('keys')}"
        print(f"  {e['status']} {e['method']:4} {path}?{q[:60]}{marker}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
