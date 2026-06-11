"""
e2e harness: boots (session-scoped) the mock identity host + mock LCR host + Supabase stub
(in-process uvicorn threads) and the REAL auth broker (uvicorn subprocess) wired to them via
the CP_TEST_MODE seam in lcr_client/hosts.py. Free ports via socket bind.

Broker env (see CLAUDE.md golden rule 1 — only test values, no secrets):
  CP_TEST_MODE=1, CP_TEST_LCR_BASE/CP_TEST_IDENTITY_BASE -> mocks, SUPABASE_URL -> stub,
  SUPABASE_SERVICE_ROLE_KEY=test-key, SUPABASE_ANON_KEY=test-anon,
  LOGIN_EVAL_BUDGET_SECONDS=30 (evals answer synchronously in tests), a throwaway
  CP_TOKEN_KEY, and NO GITHUB_TOKEN / RESEND_API_KEY / AXIOM_TOKEN (those side channels
  no-op or degrade gracefully, which is itself part of what's under test).
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
import requests

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:  # `pytest` from anywhere; `python -m pytest` already has it
    sys.path.insert(0, str(REPO))

# Env that must NEVER leak from the developer machine / CI into the broker under test.
_STRIP_ENV = (
    "GITHUB_TOKEN", "RESEND_API_KEY", "AXIOM_TOKEN", "OWNER_EMAIL", "SUPABASE_DB_URL",
    "LCR_LOGIN", "LCR_PASSWORD", "SPREADSHEET_ID", "APP_URL", "ALLOWED_ORIGINS",
    "BROKER_URL", "BROKER_PUBLIC_URL", "GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET",
    "GOOGLE_OAUTH_REDIRECT", "CP_DISABLE_CALLING_GATE", "WEBAUTHN_RP_ID",
    "SHEETS_SERVICE_ACCOUNT", "GOOGLE_SERVICE_ACCOUNT_JSON",
)


def pytest_collection_modifyitems(items):
    for item in items:
        item.add_marker(pytest.mark.timeout(240, method="thread"))


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _serve_in_thread(app, port: int):
    import uvicorn

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True,
                              name=f"mock-uvicorn-{port}")
    thread.start()
    return server


def _wait_http(url: str, timeout_s: float = 30.0, proc: subprocess.Popen | None = None,
               log_path: Path | None = None) -> None:
    deadline = time.monotonic() + timeout_s
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        if proc is not None and proc.poll() is not None:
            log = log_path.read_text(encoding="utf-8", errors="replace") if log_path else ""
            raise RuntimeError(f"server process exited with {proc.returncode}:\n{log[-4000:]}")
        try:
            if requests.get(url, timeout=2).status_code < 500:
                return
        except requests.RequestException as exc:
            last_err = exc
        time.sleep(0.25)
    raise RuntimeError(f"server at {url} did not come up in {timeout_s}s: {last_err}")


class Stack:
    """Handles + helpers for one running harness (mock hosts + stub + real broker)."""

    def __init__(self, identity_base: str, lcr_base: str, stub_base: str, broker_base: str):
        self.identity_base = identity_base
        self.lcr_base = lcr_base
        self.stub_base = stub_base
        self.broker_base = broker_base
        self.http = requests.Session()

    # -- control planes ---------------------------------------------------------------
    def reset_mocks(self) -> None:
        self.http.post(f"{self.lcr_base}/__test/reset", timeout=10).raise_for_status()
        self.http.post(f"{self.stub_base}/__test/reset", timeout=10).raise_for_status()

    def scenario(self, name: str, sleep_seconds: float | None = None) -> None:
        body: dict = {"scenario": name}
        if sleep_seconds is not None:
            body["sleep_seconds"] = sleep_seconds
        r = self.http.post(f"{self.lcr_base}/__test/control", json=body, timeout=10)
        r.raise_for_status()

    def mock_state(self) -> dict:
        return self.http.get(f"{self.lcr_base}/__test/state", timeout=10).json()

    def seed(self, **tables) -> None:
        r = self.http.post(f"{self.stub_base}/__test/seed", json=tables, timeout=10)
        r.raise_for_status()

    def stub_rows(self, table: str) -> list[dict]:
        r = self.http.get(f"{self.stub_base}/__test/rows/{table}", timeout=10)
        r.raise_for_status()
        return r.json()["rows"]

    # -- broker calls -----------------------------------------------------------------
    def login(self, username: str, password: str, enroll: bool = False) -> requests.Response:
        return self.http.post(f"{self.broker_base}/auth/password",
                              json={"username": username, "password": password,
                                    "enroll": enroll},
                              timeout=120)

    def mfa_select(self, login_id: str, factor_id: str) -> requests.Response:
        return self.http.post(f"{self.broker_base}/auth/mfa/select",
                              json={"login_id": login_id, "factor_id": factor_id}, timeout=60)

    def mfa_verify(self, login_id: str, code: str, enroll: bool = False) -> requests.Response:
        return self.http.post(f"{self.broker_base}/auth/mfa/verify",
                              json={"login_id": login_id, "code": code, "enroll": enroll},
                              timeout=120)

    def user_token(self, email: str) -> str:
        """A stub-minted Supabase user session token (generate_link -> verify, like a client)."""
        link = self.http.post(f"{self.stub_base}/auth/v1/admin/generate_link",
                              json={"type": "magiclink", "email": email}, timeout=10)
        link.raise_for_status()
        otp = link.json()["email_otp"]
        sess = self.http.post(f"{self.stub_base}/auth/v1/verify",
                              json={"type": "magiclink", "email": email, "token": otp},
                              timeout=10)
        sess.raise_for_status()
        return sess.json()["access_token"]

    def verify_minted_session(self, session: dict) -> dict:
        """Round-trip the broker-minted OTP exactly like the app: verifyOtp -> session."""
        r = self.http.post(f"{self.stub_base}/auth/v1/verify",
                           json={"type": "magiclink", "email": session["email"],
                                 "token": session["otp"]},
                           timeout=10)
        r.raise_for_status()
        return r.json()

    def audit_rows(self, **field_filters) -> list[dict]:
        rows = self.stub_rows("login_audit")
        for k, v in field_filters.items():
            rows = [r for r in rows if r.get(k) == v]
        return rows


@pytest.fixture(scope="session")
def stack() -> Stack:
    from cryptography.fernet import Fernet

    from tests.mock_lcr import build_state, create_identity_app, create_lcr_app
    from tests.supabase_stub import create_app as create_stub_app

    identity_port, lcr_port, stub_port, broker_port = (_free_port() for _ in range(4))
    identity_base = f"http://127.0.0.1:{identity_port}"
    lcr_base = f"http://127.0.0.1:{lcr_port}"
    stub_base = f"http://127.0.0.1:{stub_port}"
    broker_base = f"http://127.0.0.1:{broker_port}"

    state = build_state(identity_base=identity_base, lcr_base=lcr_base)
    servers = [
        _serve_in_thread(create_identity_app(state), identity_port),
        _serve_in_thread(create_lcr_app(state), lcr_port),
        _serve_in_thread(create_stub_app(), stub_port),
    ]
    _wait_http(f"{identity_base}/__test/state")
    _wait_http(f"{lcr_base}/__test/state")
    _wait_http(f"{stub_base}/__test/state")

    env = dict(os.environ)
    for key in _STRIP_ENV:
        env.pop(key, None)
    env.update({
        "CP_TEST_MODE": "1",
        "CP_TEST_LCR_BASE": lcr_base,
        "CP_TEST_IDENTITY_BASE": identity_base,
        "SUPABASE_URL": stub_base,
        "SUPABASE_SERVICE_ROLE_KEY": "test-key",
        "SUPABASE_ANON_KEY": "test-anon",
        "LOGIN_EVAL_BUDGET_SECONDS": "30",
        "LOGIN_GATE_BUDGET_SECONDS": "20",
        "CP_TOKEN_KEY": Fernet.generate_key().decode("ascii"),
        "PYTHONUNBUFFERED": "1",
    })
    log_path = REPO / "tools" / "output" / "e2e_broker.log"  # tools/output is gitignored
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = open(log_path, "w", encoding="utf-8")  # noqa: SIM115 — closed in teardown
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.auth_broker.app:app",
         "--host", "127.0.0.1", "--port", str(broker_port), "--log-level", "info"],
        cwd=str(REPO), env=env, stdout=log_file, stderr=subprocess.STDOUT)
    try:
        _wait_http(f"{broker_base}/health", timeout_s=90, proc=proc, log_path=log_path)
    except Exception:
        proc.kill()
        log_file.close()
        raise

    st = Stack(identity_base, lcr_base, stub_base, broker_base)
    yield st

    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    log_file.close()
    for server in servers:
        server.should_exit = True


@pytest.fixture(autouse=True)
def fresh_state(stack: Stack) -> Stack:
    """Every test starts healthy and empty: mock scenario/counters/sessions reset, stub
    tables wiped. (Broker-side in-memory state — outage tracker, refresh throttle — is
    per-username, and the tests are written to stay independent of it.)"""
    stack.reset_mocks()
    return stack
