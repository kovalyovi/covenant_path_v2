"""
Shared in-memory state for the mock identity (Okta) + mock LCR hosts.

One MockChurchState instance is shared by BOTH FastAPI apps (they run as two servers on
different ports — establish_lcr_session treats "final URL netloc == identity netloc" as the
SSO-failure signal, so the bases must differ — but the SSO handshake needs shared auth-code
state, hence one object).

Control plane (mounted on both hosts):
  POST /__test/control {"scenario": "healthy"|"lcr_5xx"|"identity_timeout"|"sso_reject"
                        [, "sleep_seconds": float]}
  GET  /__test/state    -> scenario + per-path hit counters + session counts
  POST /__test/reset    -> healthy scenario, counters/transactions/sessions cleared
"""

from __future__ import annotations

import secrets
import threading
from collections import Counter

SCENARIOS = ("healthy", "lcr_5xx", "identity_timeout", "sso_reject", "slow_access")


class MockChurchState:
    def __init__(self, identity_base: str = "", lcr_base: str = ""):
        self.identity_base = identity_base.rstrip("/")
        self.lcr_base = lcr_base.rstrip("/")
        self.lock = threading.Lock()
        self.scenario = "healthy"
        self.sleep_seconds = 70.0          # identity_timeout: longer than the callers' 60s
        self.hits: Counter = Counter()     # url path -> count (both hosts, /__test excluded)
        # Okta IDX transactions: stateHandle -> {"username", "step", "interaction_handle"}
        self.idx: dict[str, dict] = {}
        self.by_interaction: dict[str, str] = {}   # interaction_handle -> stateHandle
        self.okta_sessions: dict[str, str] = {}    # okta session cookie value -> username
        self.lcr_sessions: dict[str, str] = {}     # LCR session cookie value -> username
        self.interaction_codes: dict[str, str] = {}  # interaction_code -> username
        self.auth_codes: dict[str, str] = {}         # authorize ?code= -> username
        self.refresh_tokens: dict[str, str] = {}     # refresh_token -> username
        self.id_tokens: dict[str, str] = {}          # id_token -> username
        self.session_tokens: dict[str, str] = {}     # /api/v1/authn sessionToken -> username (web lane)

    # -- lifecycle -------------------------------------------------------------------
    def reset(self) -> None:
        with self.lock:
            self.scenario = "healthy"
            self.sleep_seconds = 70.0
            self.hits.clear()
            self.idx.clear()
            self.by_interaction.clear()
            self.okta_sessions.clear()
            self.lcr_sessions.clear()
            self.interaction_codes.clear()
            self.auth_codes.clear()
            self.refresh_tokens.clear()
            self.id_tokens.clear()
            self.session_tokens.clear()

    def set_scenario(self, scenario: str, sleep_seconds: float | None = None) -> None:
        if scenario not in SCENARIOS:
            raise ValueError(f"unknown scenario {scenario!r}; choose one of {SCENARIOS}")
        with self.lock:
            self.scenario = scenario
            if sleep_seconds is not None:
                self.sleep_seconds = float(sleep_seconds)

    def record_hit(self, path: str) -> None:
        if not path.startswith("/__test"):
            with self.lock:
                self.hits[path] += 1

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "scenario": self.scenario,
                "sleep_seconds": self.sleep_seconds,
                "hits": dict(self.hits),
                "okta_sessions": len(self.okta_sessions),
                "lcr_sessions": len(self.lcr_sessions),
                "pending_idx_transactions": len(self.idx),
                "identity_base": self.identity_base,
                "lcr_base": self.lcr_base,
            }

    # -- IDX transactions --------------------------------------------------------------
    def new_transaction(self) -> tuple[str, str]:
        """Returns (interaction_handle, state_handle) for a fresh IDX transaction."""
        ih = "ih-" + secrets.token_urlsafe(12)
        sh = "sh-" + secrets.token_urlsafe(12)
        with self.lock:
            if len(self.idx) > 256:  # opportunistic prune: tests never need this many
                self.idx.clear()
                self.by_interaction.clear()
            self.idx[sh] = {"username": None, "step": "identify", "interaction_handle": ih}
            self.by_interaction[ih] = sh
        return ih, sh

    def txn_by_interaction(self, ih: str) -> tuple[str, dict] | None:
        sh = self.by_interaction.get(ih or "")
        if sh is None:
            return None
        txn = self.idx.get(sh)
        return (sh, txn) if txn is not None else None

    def txn(self, state_handle: str) -> dict | None:
        return self.idx.get(state_handle or "")

    # -- sessions / codes ----------------------------------------------------------------
    def issue_okta_session(self, username: str) -> str:
        token = "oktasess-" + secrets.token_urlsafe(12)
        with self.lock:
            self.okta_sessions[token] = username
        return token

    def issue_interaction_code(self, username: str) -> str:
        code = "ic-" + secrets.token_urlsafe(12)
        with self.lock:
            self.interaction_codes[code] = username
        return code

    def issue_auth_code(self, username: str) -> str:
        code = "ac-" + secrets.token_urlsafe(12)
        with self.lock:
            self.auth_codes[code] = username
        return code

    def issue_lcr_session(self, username: str) -> str:
        token = "lcrsess-" + secrets.token_urlsafe(12)
        with self.lock:
            self.lcr_sessions[token] = username
        return token

    def issue_session_token(self, username: str) -> str:
        """The classic /api/v1/authn sessionToken — redeemed at the OAuth /authorize?sessionToken=
        leg the web_session (credential-capture / one-MFA) flow uses."""
        token = "st-" + secrets.token_urlsafe(12)
        with self.lock:
            self.session_tokens[token] = username
        return token

    def issue_tokens(self, username: str) -> dict:
        rt = "rt-" + secrets.token_urlsafe(12)
        idt = "idt-" + secrets.token_urlsafe(12)
        with self.lock:
            self.refresh_tokens[rt] = username
            self.id_tokens[idt] = username
        return {
            "token_type": "Bearer",
            "expires_in": 3600,
            "access_token": "at-" + secrets.token_urlsafe(12),
            "scope": "openid profile email offline_access cmisid group",
            "id_token": idt,
            "refresh_token": rt,
        }
