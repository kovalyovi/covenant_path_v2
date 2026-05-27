"""
One-time capture: find the server action that returns a WARD's leadership (bishopric,
EQ/RS presidencies). The stake leadership action returns only the stake org, so we open
the orgs page and drill into a ward, recording every /mlt server-action POST + whether
its response contains ward-level positions (Bishop=4, EQ Pres=138, RS Pres=143).

Usage: python tools/capture_ward_leadership.py
"""

import json
import re
import sys
from pathlib import Path

STATE = Path(__file__).resolve().parent / "output" / "storage_state.json"
OUT = Path(__file__).resolve().parent / "output" / "_ward_leadership_capture.json"
BASE = "https://lcr.churchofjesuschrist.org"
WARD_ROLE_IDS = {4, 54, 138, 143, 183, 204, 210}  # bishopric/quorum/aux presidencies


def ward_positions(text: str) -> dict:
    pairs = {}
    for m in re.finditer(r'"positionType":\{"id":(\d+),"name":"([^"]+)"', text):
        rid = int(m.group(1))
        if rid in WARD_ROLE_IDS:
            pairs[rid] = m.group(2)
    return pairs


def main() -> int:
    from playwright.sync_api import sync_playwright
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
            wp = ward_positions(body)
            try:
                post = (req.post_data or "")[:200]
            except Exception:
                post = "<binary>"
            captured.append({"action": na, "url": req.url, "post": post,
                             "state_tree": req.headers.get("next-router-state-tree", "")[:400],
                             "ward_positions": wp})

        ctx.on("response", on_response)
        url = f"{BASE}/mlt/orgs?unitTypeId=7,8&list=true&leadership=true&lang=eng"
        print(f"[*] opening {url}")
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        try:
            page.wait_for_load_state("networkidle", timeout=25000)
        except Exception:
            pass
        page.wait_for_timeout(2500)

        # try drilling into wards: click expandable rows / unit links / disclosure buttons
        for sel in ["[role=button]", "button", "a", "[role=treeitem]", "summary", "li"]:
            try:
                els = page.locator(sel)
                for i in range(min(els.count(), 25)):
                    try:
                        t = (els.nth(i).inner_text(timeout=500) or "").strip()
                    except Exception:
                        continue
                    if any(w in t for w in ("Ward", "Branch", "Bishopric", "Quorum", "Relief Society")):
                        try:
                            els.nth(i).click(timeout=1500)
                            page.wait_for_timeout(1200)
                        except Exception:
                            continue
            except Exception:
                continue
        page.wait_for_timeout(2000)
        browser.close()

    OUT.write_text(json.dumps(captured, indent=2, ensure_ascii=False), encoding="utf-8")
    hits = [c for c in captured if c["ward_positions"]]
    print(f"[+] {len(captured)} server-action POSTs, {len(hits)} with ward positions -> {OUT}")
    for c in captured:
        wp = c["ward_positions"]
        print(f"   action={c['action'][:16]}.. args={c['post'][:60]} wardpos={list(wp.values())[:4]}")
    if hits:
        b = max(hits, key=lambda c: len(c["ward_positions"]))
        print(f"\n[+] ward-leadership action: {b['action']}\n    args: {b['post']}\n    state_tree: {b['state_tree'][:160]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
