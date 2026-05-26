"""
LCR API Discovery Crawler (Phase 0).

Drives lcr.churchofjesuschrist.org with Playwright, intercepts every XHR/fetch
call the LCR frontend makes, and catalogs each endpoint: method, normalized
path, query keys, request/response content types, response shape, and whether
it needs auth. Produces the inputs for generating the Phase 1 Python client.

Outputs (under tools/output/, gitignored):
  lcr_endpoints.json   machine-readable endpoint catalog
  lcr_api_catalog.md   human-readable catalog
  storage_state.json   authenticated browser session (cookies + localStorage)
  auth_token.txt       latest captured Bearer token (for the Phase 1 client)

Setup:
  pip install -r requirements.txt
  playwright install chromium
  cp .env.example .env   # then fill in LCR_LOGIN / LCR_PASSWORD

Usage:
  python tools/lcr_crawler.py              # headed: auto-login, auto-crawl, then manual-assist
  python tools/lcr_crawler.py --no-manual  # auto phase only, no manual pause
  python tools/lcr_crawler.py --headless   # implies --no-manual
  python tools/lcr_crawler.py --no-login   # reuse saved storage_state.json (skip login)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
from playwright.sync_api import Response, TimeoutError as PWTimeout, sync_playwright

BASE_URL = "https://lcr.churchofjesuschrist.org"
OUTPUT_DIR = Path(__file__).parent / "output"

# Pages to auto-visit (Phase 1-3). From the master plan, plus v1's progress-record.
KNOWN_PATHS = [
    "/records/member-list",
    "/records/individual-photo",
    "/records/move-in",
    "/records/move-out",
    "/records/out-of-unit-members",
    "/report/action-interview-list",
    "/report/ministering",
    "/report/quarterly-report",
    "/report/progress-record",
    "/one-work/progress-record",
    "/report/attendance",
    "/report/sacrament-meeting-attendance",
    "/report/seminary",
    "/calling/overview",
    "/finances/expense",
    "/finances/budget",
    "/map/ward",
]

UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def normalize_path(path: str) -> str:
    """Collapse id-like path segments so member/unit ids group into one endpoint."""
    out = []
    for seg in path.split("/"):
        if not seg:
            out.append(seg)
        elif UUID_RE.match(seg):
            out.append("{uuid}")
        elif seg.isdigit():
            out.append("{id}")
        elif re.match(r"^[0-9a-fA-F]{16,}$", seg):
            out.append("{hash}")
        else:
            out.append(seg)
    return "/".join(out)


def response_shape(body):
    """Summarize the top-level shape of a parsed JSON body."""
    if isinstance(body, dict):
        return {"type": "object", "keys": sorted(body.keys())}
    if isinstance(body, list):
        first = body[0] if body else None
        item_keys = sorted(first.keys()) if isinstance(first, dict) else None
        return {"type": "array", "length": len(body), "item_keys": item_keys}
    return {"type": type(body).__name__}


class Catalog:
    """Deduplicating store of observed API endpoints, keyed by method+host+path."""

    def __init__(self):
        self.endpoints: dict[tuple, dict] = {}
        self.latest_token: str | None = None

    def record(self, response: Response) -> None:
        req = response.request
        if req.resource_type not in ("xhr", "fetch"):
            ctype = (response.headers or {}).get("content-type", "")
            if "application/json" not in ctype:
                return

        parsed = urlparse(req.url)
        if not parsed.hostname or "churchofjesuschrist.org" not in parsed.hostname:
            return

        auth = req.headers.get("authorization")
        if auth and auth.lower().startswith("bearer "):
            self.latest_token = auth.split(" ", 1)[1]

        norm = normalize_path(parsed.path)
        key = (req.method, parsed.hostname, norm)
        entry = self.endpoints.get(key)
        if entry is None:
            entry = {
                "method": req.method,
                "host": parsed.hostname,
                "path": norm,
                "example_url": req.url,
                "statuses": set(),
                "query_keys": set(),
                "requires_auth": False,
                "request_content_type": None,
                "request_body_sample": None,
                "response_content_type": None,
                "response_shape": None,
                "response_sample": None,
                "count": 0,
            }
            self.endpoints[key] = entry

        entry["count"] += 1
        entry["statuses"].add(response.status)
        entry["requires_auth"] = entry["requires_auth"] or bool(auth)
        for k in (parsed.query or "").split("&"):
            if k:
                entry["query_keys"].add(k.split("=", 1)[0])

        if req.post_data and entry["request_body_sample"] is None:
            entry["request_content_type"] = req.headers.get("content-type")
            entry["request_body_sample"] = req.post_data[:1000]

        if entry["response_sample"] is None:
            entry["response_content_type"] = (response.headers or {}).get("content-type")
            try:
                body = response.json()
                entry["response_shape"] = response_shape(body)
                entry["response_sample"] = json.dumps(body)[:2000]
            except Exception:
                try:
                    entry["response_sample"] = response.text()[:2000]
                except Exception:
                    pass

    def to_list(self) -> list[dict]:
        rows = []
        for entry in self.endpoints.values():
            row = dict(entry)
            row["statuses"] = sorted(row["statuses"])
            row["query_keys"] = sorted(row["query_keys"])
            rows.append(row)
        rows.sort(key=lambda r: (r["host"], r["path"], r["method"]))
        return rows


def attempt_login(page, login: str, password: str) -> bool:
    """Automated username/password login (password-only accounts, no 2FA)."""
    print("[*] Logging in...")
    page.goto(f"{BASE_URL}/", wait_until="domcontentloaded")
    try:
        page.wait_for_selector("#username-input", timeout=20000)
        page.click("#username-input")
        page.fill("#username-input", login)
        page.click("#button-primary")
        page.wait_for_selector("#password-input", timeout=20000)
        page.fill("#password-input", password)
        page.click("#button-primary")
        page.wait_for_url(re.compile(r"lcr\.churchofjesuschrist\.org"), timeout=30000)
        page.wait_for_load_state("networkidle", timeout=30000)
        print("[+] Login submitted.")
        return True
    except PWTimeout:
        print("[!] Automated login selectors not found / timed out.")
        return False


def crawl_known_pages(page) -> None:
    for path in KNOWN_PATHS:
        url = f"{BASE_URL}{path}"
        print(f"[*] Visiting {path}")
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except PWTimeout:
                pass
            click_tabs(page)
        except PWTimeout:
            print(f"[!] Timeout visiting {path}")
        except Exception as exc:  # noqa: BLE001
            print(f"[!] Error visiting {path}: {exc}")


def click_tabs(page) -> None:
    """Best-effort: click ARIA tabs on the current page to trigger their loads."""
    try:
        tabs = page.get_by_role("tab")
        count = min(tabs.count(), 12)
    except Exception:  # noqa: BLE001
        return
    for i in range(count):
        try:
            tabs.nth(i).click(timeout=2000)
            page.wait_for_timeout(1200)
        except Exception:  # noqa: BLE001
            continue


def export(catalog: Catalog) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = catalog.to_list()

    (OUTPUT_DIR / "lcr_endpoints.json").write_text(
        json.dumps(rows, indent=2), encoding="utf-8"
    )

    lines = [
        "# LCR API Catalog",
        "",
        f"Discovered {len(rows)} unique endpoints.",
        "",
    ]
    for r in rows:
        lines.append(f"## `{r['method']} {r['path']}`")
        lines.append("")
        lines.append(f"- Host: `{r['host']}`")
        lines.append(f"- Statuses: {r['statuses']}")
        lines.append(f"- Requires auth: {r['requires_auth']}")
        lines.append(f"- Seen: {r['count']}x")
        if r["query_keys"]:
            lines.append(f"- Query keys: {', '.join(r['query_keys'])}")
        if r["request_body_sample"]:
            lines.append(f"- Request body sample: `{r['request_body_sample'][:300]}`")
        if r["response_shape"]:
            lines.append(f"- Response shape: `{json.dumps(r['response_shape'])}`")
        if r["response_sample"]:
            lines.append("- Response sample:")
            lines.append("")
            lines.append("```json")
            lines.append(r["response_sample"])
            lines.append("```")
        lines.append("")
    (OUTPUT_DIR / "lcr_api_catalog.md").write_text("\n".join(lines), encoding="utf-8")

    if catalog.latest_token:
        (OUTPUT_DIR / "auth_token.txt").write_text(
            catalog.latest_token, encoding="utf-8"
        )

    print(f"\n[+] Wrote {len(rows)} endpoints to {OUTPUT_DIR}")
    print("    - lcr_endpoints.json")
    print("    - lcr_api_catalog.md")
    if catalog.latest_token:
        print("    - auth_token.txt (Bearer token captured)")


def main() -> int:
    parser = argparse.ArgumentParser(description="LCR API discovery crawler")
    parser.add_argument("--headless", action="store_true", help="run headless (implies --no-manual)")
    parser.add_argument("--no-manual", action="store_true", help="skip the manual-assist pause")
    parser.add_argument("--no-login", action="store_true", help="reuse saved storage_state.json")
    args = parser.parse_args()

    load_dotenv()
    login = os.getenv("LCR_LOGIN")
    password = os.getenv("LCR_PASSWORD")
    state_path = OUTPUT_DIR / "storage_state.json"

    if not args.no_login and (not login or not password):
        print("[!] LCR_LOGIN / LCR_PASSWORD not set. Add them to .env or use --no-login.")
        return 1

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    catalog = Catalog()
    headless = args.headless
    manual = not (args.no_manual or headless)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        ctx_kwargs = {}
        if args.no_login and state_path.exists():
            ctx_kwargs["storage_state"] = str(state_path)
        context = browser.new_context(**ctx_kwargs)
        context.on("response", lambda r: _safe_record(catalog, r))
        page = context.new_page()

        try:
            if not args.no_login:
                if not attempt_login(page, login, password):
                    if manual:
                        input("\n>>> Log in manually in the browser, then press Enter to continue... ")
                    else:
                        print("[!] Login failed and no manual mode. Aborting.")
                        return 1
                context.storage_state(path=str(state_path))

            crawl_known_pages(page)

            if manual:
                print("\n" + "=" * 64)
                print("MANUAL ASSIST: click member rows, open modals, submit forms,")
                print("switch wards/units, paginate. Every API call is being captured.")
                print("Press Enter here when you're done.")
                print("=" * 64)
                input(">>> ")
                context.storage_state(path=str(state_path))
        finally:
            export(catalog)
            browser.close()

    return 0


def _safe_record(catalog: Catalog, response: Response) -> None:
    try:
        catalog.record(response)
    except Exception:  # noqa: BLE001
        pass


if __name__ == "__main__":
    sys.exit(main())
