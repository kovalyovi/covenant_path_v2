"""
Capture the LCR/Okta login flow in detail (investigation).

Fresh browser context, navigate to LCR, complete the login form, and record
every request/response/cookie across the auth hosts (id./op./www.churchofjesuschrist.org)
— interact, introspect, identify, challenge, challenge/answer, token, and the
redirects that set the LCR session cookie. Dump a full trace so we can replicate
the Okta IDX + PKCE flow in plain requests.

Usage:
  python tools/capture_login.py
"""

import json
import os
import sys
from urllib.parse import urlparse

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

AUTH_HOSTS = ("id.churchofjesuschrist.org", "op.churchofjesuschrist.org",
              "www.churchofjesuschrist.org", "lcr.churchofjesuschrist.org",
              "mltp-api.churchofjesuschrist.org")
OUT = os.path.join(os.path.dirname(__file__), "output")
trace = []


def safe_post(req):
    try:
        return req.post_data
    except Exception:
        return "<binary>"


def main():
    load_dotenv()
    login = os.getenv("LCR_LOGIN")
    password = os.getenv("LCR_PASSWORD")
    if not login or not password:
        print("[!] LCR_LOGIN / LCR_PASSWORD not set")
        return 1

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context()  # fresh, no cookies
        page = ctx.new_page()

        def on_response(resp):
            req = resp.request
            host = urlparse(req.url).hostname or ""
            if not any(host == h for h in AUTH_HOSTS):
                return
            path = urlparse(req.url).path
            interesting = any(k in path for k in
                              ("interact", "introspect", "identify", "challenge",
                               "token", "authorize", "/login", "/auth"))
            entry = {
                "method": req.method,
                "url": req.url,
                "status": resp.status,
                "req_ctype": req.headers.get("content-type"),
                "post": (safe_post(req) or "")[:600] if interesting else None,
                "set_cookie": resp.headers.get("set-cookie", "")[:300] or None,
                "location": resp.headers.get("location"),
            }
            if interesting and resp.status == 200:
                try:
                    entry["resp_json"] = json.dumps(resp.json())[:1200]
                except Exception:
                    entry["resp_text"] = (resp.text() or "")[:300]
            trace.append(entry)

        ctx.on("response", on_response)

        print("[*] navigating to LCR (fresh context)...")
        page.goto("https://lcr.churchofjesuschrist.org/", wait_until="domcontentloaded", timeout=60000)
        # try the church custom Okta widget selectors
        try:
            page.wait_for_selector("#username-input, input[name='identifier']", timeout=15000)
            print("[*] login form present — submitting credentials")
            user_sel = "#username-input" if page.query_selector("#username-input") else "input[name='identifier']"
            page.fill(user_sel, login)
            for sel in ("#button-primary", "input[type='submit']", "button[type='submit']"):
                if page.query_selector(sel):
                    page.click(sel)
                    break
            page.wait_for_selector("#password-input, input[name='credentials.passcode']", timeout=15000)
            pass_sel = "#password-input" if page.query_selector("#password-input") else "input[name='credentials.passcode']"
            page.fill(pass_sel, password)
            for sel in ("#button-primary", "input[type='submit']", "button[type='submit']"):
                if page.query_selector(sel):
                    page.click(sel)
                    break
        except Exception as exc:
            print(f"[!] login form not found / already authenticated: {exc}")
        try:
            page.wait_for_url(lambda u: "lcr.churchofjesuschrist.org" in u and "/sign-in" not in u, timeout=30000)
        except Exception:
            pass
        try:
            page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass
        cookies = ctx.cookies()
        browser.close()

    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "_login_trace.json"), "w", encoding="utf-8") as fh:
        json.dump({"trace": trace, "final_cookies": [c["name"] + "@" + c["domain"] for c in cookies]},
                  fh, indent=2)

    print(f"\n=== {len(trace)} auth-host responses ===")
    for e in trace:
        p = urlparse(e["url"]).path
        host = urlparse(e["url"]).hostname
        sc = " +set-cookie" if e["set_cookie"] else ""
        loc = f" -> {e['location']}" if e.get("location") else ""
        print(f"  {e['status']} {e['method']:4} {host}{p}{sc}{loc}")
        if e.get("post"):
            print(f"       POST: {e['post'][:200]}")
        if e.get("resp_json"):
            print(f"       RESP: {e['resp_json'][:200]}")
    print(f"\nfinal cookies: {len(cookies)}; full trace -> tools/output/_login_trace.json")


if __name__ == "__main__":
    sys.exit(main())
