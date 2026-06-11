"""
Single source for the Church host base URLs (LCR + the id.* Okta/identity host).

PRODUCTION IS PINNED: the CP_TEST_* overrides are read ONLY when CP_TEST_MODE=1, so a stray
environment variable on a real deployment (the broker handles live credentials) can never
redirect logins or scraping to another host. CP_TEST_MODE must never be set on Render/CI-sync —
it exists solely so the e2e suite (tests/) can point the REAL client/broker code at the local
mock LCR/Okta (tests/mock_lcr) and exercise full login/enroll/sync flows without Church
credentials.

Everything that needs a Church URL derives it from LCR_BASE / IDENTITY_BASE; the helpers below
keep the "is this the Okta host?" and "is this a Church cookie?" checks working when the bases
point at localhost mocks (where both hosts differ only by port).
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

_TEST_MODE = os.environ.get("CP_TEST_MODE") == "1"


def _base(env_name: str, default: str) -> str:
    if _TEST_MODE:
        return (os.environ.get(env_name) or default).rstrip("/")
    return default


LCR_BASE = _base("CP_TEST_LCR_BASE", "https://lcr.churchofjesuschrist.org")
IDENTITY_BASE = _base("CP_TEST_IDENTITY_BASE", "https://id.churchofjesuschrist.org")


def is_identity_host(url: str) -> bool:
    """True when `url` lives on the Okta/identity host — the "SSO landed back on Okta" signal.
    Netloc-compares against IDENTITY_BASE (so it holds for a localhost mock, which differs from
    the mock LCR only by port) and keeps the legacy id.* prefix check for production."""
    p = urlparse(url or "")
    return (bool(p.netloc) and p.netloc == urlparse(IDENTITY_BASE).netloc) or (
        (p.hostname or "").startswith("id."))


def cookie_domains() -> tuple[str, ...]:
    """Domains whose cookies count as Church-session cookies. In test mode the mock hosts'
    domains join the list so session capture/persist works against localhost."""
    doms = ["churchofjesuschrist.org"]
    if _TEST_MODE:
        for base in (LCR_BASE, IDENTITY_BASE):
            host = urlparse(base).hostname or ""
            if host and "churchofjesuschrist.org" not in host and host not in doms:
                doms.append(host)
    return tuple(doms)


def is_church_cookie_domain(domain: str | None) -> bool:
    d = (domain or "").lstrip(".")
    return any(allowed in d for allowed in cookie_domains())
