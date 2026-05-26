"""
Generic page-API capture (investigation).

Logs in, navigates to a given LCR path, and records every XHR/fetch/document
request plus server-action POSTs and their responses, so we can find the data
source behind a report page (JSON API or Next.js server action) and then replay
it with plain requests.

Usage:
  python tools/capture_page_api.py "/temple/recommend/recommend-status?lang=eng" [keyword ...]
"""

import os
import sys
from urllib.parse import urlparse

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

sys.path.insert(0, os.path.dirname(__file__))
from lcr_crawler import attempt_login

BASE = "https://lcr.churchofjesuschrist.org"
PATH = sys.argv[1] if len(sys.argv) > 1 else "/temple/recommend/recommend-status?lang=eng"
KEYWORDS = sys.argv[2:] or ["recommend", "expir", "Active", "Expired", "minister",
                            "companionship", "assignment"]
OUT = os.path.join(os.path.dirname(__file__), "output")
STATE = os.path.join(OUT, "storage_state.json")

events = []


def main():
    load_dotenv()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context()
        page = ctx.new_page()
        attempt_login(page, os.getenv("LCR_LOGIN"), os.getenv("LCR_PASSWORD"))

        seen = []

        def _safe_post(req):
            try:
                return (req.post_data or "")[:140]
            except Exception:
                return "<binary>"

        def on_request(req):
            if req.resource_type in ("xhr", "fetch", "document"):
                seen.append((req.resource_type, req.method, req.url,
                             req.headers.get("next-action"), _safe_post(req)))

        def on_response(resp):
            req = resp.request
            ct = (resp.headers or {}).get("content-type", "")
            if not any(t in ct for t in ("json", "x-component", "html")):
                return
            host = urlparse(req.url).hostname or ""
            if "churchofjesuschrist.org" not in host:
                return
            try:
                body = resp.text()
            except Exception:
                return
            hits = [k for k in KEYWORDS if k.lower() in body.lower()]
            events.append({"method": req.method, "url": req.url, "ct": ct,
                           "na": req.headers.get("next-action"),
                           "post": _safe_post(req),
                           "len": len(body), "hits": hits, "body": body})

        ctx.on("request", on_request)
        ctx.on("response", on_response)
        page.goto(f"{BASE}{PATH}", wait_until="domcontentloaded", timeout=60000)
        try:
            page.wait_for_load_state("networkidle", timeout=25000)
        except Exception:
            pass
        page.wait_for_timeout(3000)
        ctx.storage_state(path=STATE)
        browser.close()

    print(f"\n=== {len(seen)} xhr/fetch/document requests ===")
    for t, m, u, na, post in seen:
        pq = urlparse(u)
        tag = f" NEXT-ACTION={na}" if na else ""
        pp = f" POST={post}" if post else ""
        print(f"  {t:8} {m:5} {pq.hostname}{pq.path}{tag}{pp}")

    print(f"\n=== {len(events)} responses; data-bearing (>=2 keyword hits): ===")
    for i, e in enumerate(events):
        if len(e["hits"]) >= 2:
            pq = urlparse(e["url"])
            fn = os.path.join(OUT, f"_page_{i}.txt")
            open(fn, "w", encoding="utf-8").write(
                f"{e['method']} {e['url']}\nNEXT-ACTION: {e['na']}\nPOST: {e['post']}\n\n{e['body']}")
            print(f"  [{i}] {e['method']} {pq.path}  na={e['na']}  len={e['len']}  hits={e['hits']}  -> _page_{i}.txt")


if __name__ == "__main__":
    main()
