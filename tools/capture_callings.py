"""
One-time capture of the /mlt callings/leadership server action (investigation).

The member-callings / leadership pages are App-Router pages whose data loads via a
Next.js Server Action POST (like member-profile). This injects the existing session
cookies into a headless browser, opens the page, and records every server-action
POST + response so we can (a) harvest positionType {id,name} pairs to complete the
role-name catalog and (b) learn the action id / args / state-tree to replay it in
pure requests.

Usage:
  python tools/capture_callings.py [url]
  (default url: /mlt/report/member-callings)
"""

import json
import re
import sys
from pathlib import Path

STATE = Path(__file__).resolve().parent / "output" / "storage_state.json"
OUT = Path(__file__).resolve().parent / "output" / "_callings_capture.json"
BASE = "https://lcr.churchofjesuschrist.org"


def positiontype_pairs(text: str) -> dict:
    pairs = {}
    for m in re.finditer(r'"positionType":\{"id":(\d+),"name":"([^"]+)"', text):
        pairs[int(m.group(1))] = m.group(2)
    return pairs


def main() -> int:
    from playwright.sync_api import sync_playwright

    url = sys.argv[1] if len(sys.argv) > 1 else "/mlt/report/member-callings?lang=eng"
    if url.startswith("/"):
        url = BASE + url
    captured = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(storage_state=str(STATE))
        page = ctx.new_page()

        def on_response(resp):
            req = resp.request
            if req.method != "POST" or "/mlt/" not in req.url:
                return
            na = req.headers.get("next-action")
            if not na:
                return
            try:
                body = resp.text()
            except Exception:
                return
            pairs = positiontype_pairs(body)
            captured.append({
                "action": na,
                "url": req.url,
                "post": (req.post_data or "")[:300],
                "state_tree": req.headers.get("next-router-state-tree", "")[:300],
                "status": resp.status,
                "positiontype_pairs": len(pairs),
                "pairs": pairs,
            })

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
    print(f"\n[+] captured {len(captured)} server-action POSTs -> {OUT}")
    best = max(captured, key=lambda c: c["positiontype_pairs"], default=None)
    for c in captured:
        print(f"   action={c['action'][:18]}.. status={c['status']} "
              f"positionType_pairs={c['positiontype_pairs']}  args={c['post'][:80]}")
    if best and best["positiontype_pairs"]:
        print(f"\n[+] richest action: {best['action']} "
              f"({best['positiontype_pairs']} positionType pairs)")
        print(f"    args: {best['post']}")
        print(f"    state_tree: {best['state_tree'][:120]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
