"""
E2E login timing against the PRODUCTION web app (#6 — the ">75s to sign in" report).

Drives a real Chromium through the Church-account form at APP_URL in a FRESH browser context per
run (no cookies/session = the incognito case) and measures what the user actually feels:

  t_form   first navigation -> login form interactive
  t_login  click "Sign in"  -> Supabase session adopted (the login card unmounts)   <- THE number
  t_paint  ...              -> dashboard painted real content (best-effort marker)

Budget: t_login <= 5s on a warm broker with a cached identity (ADR-009 fast lane).

Usage:
    pip install playwright && python -m playwright install chromium
    python tools/e2e_login_timing.py [runs]

Reads LCR_LOGIN / LCR_PASSWORD (and optional APP_URL) from .env — credentials are never printed.
"""

from __future__ import annotations

import os
import sys
import time

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv()
APP_URL = os.environ.get("APP_URL", "https://app.membercovenantpath.org").strip('"')
USER = os.environ["LCR_LOGIN"]
PASSWORD = os.environ["LCR_PASSWORD"]


def one_run(pw, n: int) -> dict:
    browser = pw.chromium.launch()
    ctx = browser.new_context()  # fresh = no session, like incognito
    page = ctx.new_page()
    page.on("console", lambda m: m.text.startswith("[login-timing]") and print(f"    {m.text}"))
    t_nav = time.perf_counter()
    page.goto(APP_URL, wait_until="domcontentloaded")
    page.wait_for_selector('input[name="church-username"]', timeout=30_000)
    t_form = time.perf_counter()
    page.fill('input[name="church-username"]', USER)
    page.fill('input[type="password"]', PASSWORD)
    t_click = time.perf_counter()
    page.get_by_role("button", name="Sign in", exact=True).click()
    # Session adopted == the login card unmounts (router swaps to the app shell).
    page.wait_for_selector(".login-card", state="detached", timeout=150_000)
    t_login = time.perf_counter()
    t_paint = None
    try:  # best-effort: some real dashboard content (stake header/table) painted
        page.wait_for_selector("main :text-matches('Stake|members|Dashboard', 'i')", timeout=20_000)
        t_paint = time.perf_counter()
    except Exception:  # noqa: BLE001 — marker miss is fine; t_login is the budgeted number
        pass
    out = {
        "form_ms": round((t_form - t_nav) * 1000),
        "login_ms": round((t_login - t_click) * 1000),
        "paint_ms": round((t_paint - t_click) * 1000) if t_paint else None,
    }
    print(f"  run {n}: form {out['form_ms']}ms | click->session {out['login_ms']}ms"
          f" | click->painted {out['paint_ms'] or '—'}ms")
    ctx.close()
    browser.close()
    return out


def main() -> int:
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    print(f"e2e login timing vs {APP_URL} ({runs} fresh-context runs)")
    results = []
    with sync_playwright() as pw:
        for i in range(1, runs + 1):
            results.append(one_run(pw, i))
    budget = [r["login_ms"] for r in results]
    print(f"click->session: {budget} ms — budget 5000ms -> "
          f"{'PASS' if all(b <= 5000 for b in budget[1:] or budget) else 'CHECK'}"
          f" (first run may take the full-identity path once)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
