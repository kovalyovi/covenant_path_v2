"""
LCR session auth.

LCR authenticates with an Okta session cookie (no Bearer header), so the client
reuses cookies captured by the Phase 0 crawler's Playwright session
(tools/output/storage_state.json) inside a requests.Session.

A fresh session is minted headlessly via lcr_client.okta_login (pure requests,
no browser). LcrSession does this automatically when no session file exists
(auto_login=True) and `relogin()` re-mints on expiry. The Playwright crawler
(`python tools/lcr_crawler.py`) remains a manual fallback.

When the session expires, LCR redirects API calls to the id.churchofjesuschrist.org
login page (returning HTML instead of JSON); that is surfaced as AuthExpiredError.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import requests

DEFAULT_STORAGE_STATE = (
    Path(__file__).resolve().parent.parent / "tools" / "output" / "storage_state.json"
)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36"
)


class AuthExpiredError(RuntimeError):
    """Raised when the LCR session cookies are no longer valid."""


class LcrSession:
    """A requests.Session preloaded with LCR cookies, with auth-expiry detection."""

    def __init__(
        self,
        storage_state_path: str | Path = DEFAULT_STORAGE_STATE,
        lang: str = "eng",
        auto_login: bool = True,
    ) -> None:
        self.lang = lang
        self.auto_login = auto_login
        self.storage_state_path = Path(storage_state_path)
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": USER_AGENT, "Accept": "application/json, text/plain, */*"}
        )
        if not self.storage_state_path.exists() and auto_login:
            self.relogin()
        else:
            self._load_cookies()

    def relogin(self) -> None:
        """Mint a fresh session headlessly (pure-requests Okta), then load it."""
        from lcr_client.okta_login import login

        login(storage_state_path=self.storage_state_path)
        self.reload()

    def _read_state_cookies(self) -> list[dict]:
        if not self.storage_state_path.exists():
            raise FileNotFoundError(
                f"No session file at {self.storage_state_path}. "
                "Run `python -m lcr_client.okta_login` (or tools/lcr_crawler.py) to create one."
            )
        state = json.loads(self.storage_state_path.read_text(encoding="utf-8"))
        return state.get("cookies", []) or []

    def _load_cookies(self) -> None:
        self._set_cookies(self._read_state_cookies())

    def _set_cookies(self, cookies: list[dict]) -> None:
        for c in cookies:
            self.session.cookies.set(
                c["name"],
                c["value"],
                domain=c.get("domain"),
                path=c.get("path", "/"),
            )

    def reload(self) -> None:
        """Re-read cookies from storage_state (after a fresh browser login refreshed it).

        NON-DESTRUCTIVE, and that is the whole point: this used to clear the jar and *then* read the
        file, so a session with no file on disk was left holding NO cookies at all — silently
        unauthenticated, with every later call failing fast and logging nothing. The broker's
        delegated session is exactly that: `_client_from_cookies` injects the captured cookies and
        deletes its temp state file. On 2026-08-30 one member's 404 triggered an action-id heal
        whose trailing reload() wiped the freshly-captured session, and the remaining 8 members of
        the fill failed instantly ("0/9 -> needs_reauth") — telling a leader who had just
        re-authorized to re-authorize again. Read first, swap only on success; no file is a no-op."""
        try:
            fresh = self._read_state_cookies()
        except FileNotFoundError:
            return  # injected-cookie session (no file to reload from) — keep what we have
        if not fresh:
            return  # an empty state file is not a reason to throw away a working session
        self.session.cookies.clear()
        self._set_cookies(fresh)

    def get_json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        """GET a URL expecting JSON; inject lang; raise AuthExpiredError on login redirect."""
        params = {"lang": self.lang, **(params or {})}

        def _do():
            import time as _t
            from lcr_client import metrics
            t0 = _t.perf_counter()
            try:
                resp = self.session.get(url, params=params, timeout=60)
            except Exception as exc:  # noqa: BLE001 — record timeouts/conn errors too
                metrics.record(url, 0, (_t.perf_counter() - t0) * 1000, error=type(exc).__name__)
                raise
            metrics.record(url, resp.status_code, (_t.perf_counter() - t0) * 1000)
            self._check_auth(resp)
            resp.raise_for_status()
            return resp.json()

        return self._with_relogin(_do)

    def post_json(self, url: str, params: dict[str, Any] | None = None, json_body: Any = None) -> Any:
        params = {"lang": self.lang, **(params or {})}

        def _do():
            import time as _t
            from lcr_client import metrics
            t0 = _t.perf_counter()
            try:
                resp = self.session.post(url, params=params, json=json_body, timeout=60)
            except Exception as exc:  # noqa: BLE001 — record timeouts/conn errors too
                metrics.record(url, 0, (_t.perf_counter() - t0) * 1000, error=type(exc).__name__)
                raise
            metrics.record(url, resp.status_code, (_t.perf_counter() - t0) * 1000)
            self._check_auth(resp)
            resp.raise_for_status()
            return resp.json()

        return self._with_relogin(_do)

    def get_text(self, url: str, params: dict[str, Any] | None = None) -> str:
        """GET a URL expecting HTML/text; auto-recover on auth expiry.

        Used for the access-table page (legitimately text/html), so expiry is
        detected by a redirect to the id.churchofjesuschrist.org login host rather
        than by content-type (which would false-positive on real HTML pages).
        """
        params = {"lang": self.lang, **(params or {})}

        def _do():
            resp = self.session.get(url, params=params, timeout=60)
            from lcr_client.hosts import is_identity_host
            if resp.status_code in (401, 403) or is_identity_host(resp.url):
                raise AuthExpiredError(
                    "LCR redirected to login (session expired) while fetching a page."
                )
            resp.raise_for_status()
            return resp.text

        return self._with_relogin(_do)

    def _with_relogin(self, call):
        """Run a request; on auth expiry, re-mint the session once and retry."""
        try:
            return call()
        except AuthExpiredError:
            if not self.auto_login:
                raise
            self.relogin()
            return call()

    @staticmethod
    def _check_auth(resp: requests.Response) -> None:
        if resp.status_code in (401, 403):
            raise AuthExpiredError(
                f"LCR returned {resp.status_code}. Session expired — "
                "re-run `python tools/lcr_crawler.py`."
            )
        from lcr_client.hosts import is_identity_host
        ctype = resp.headers.get("content-type", "")
        if is_identity_host(resp.url) or (
            "application/json" not in ctype and "text/html" in ctype
        ):
            raise AuthExpiredError(
                "LCR redirected to login (session expired). "
                "Re-run `python tools/lcr_crawler.py`."
            )
