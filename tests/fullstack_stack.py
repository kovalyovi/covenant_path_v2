"""
FULLSTACK-lane stack runner (Phase B): one command that boots everything the Playwright
`fullstack` project needs BEHIND the web app —

    mock identity (Okta IDX)  :8921   tests/mock_lcr
    mock LCR                  :8922   tests/mock_lcr
    the REAL auth broker      :8924   backend.auth_broker.app (uvicorn subprocess)

wired together exactly like tests/e2e/conftest.py (whose helpers this reuses), with ONE
difference: there is NO supabase_stub here — SUPABASE_URL points at the dedicated **test**
Supabase project (CP_TEST_SUPABASE_URL), so session minting, the identity cache, the enroll
RPC, login_audit and RLS are all REAL Postgres. The web app (vite) is started by Playwright
itself (see apps/web/playwright.config.ts) against the same test project + this broker.

Env (read from the repo .env via dotenv; process env wins; values are NEVER printed):
    CP_TEST_SUPABASE_URL / CP_TEST_SUPABASE_ANON_KEY / CP_TEST_SUPABASE_SERVICE_ROLE_KEY
Refuses to run when they're missing or when the test URL equals the prod SUPABASE_URL.
The broker subprocess gets NO GITHUB_TOKEN / RESEND_API_KEY etc. (conftest._STRIP_ENV), so
the on-enroll kickoff and emails no-op — github_configured() is false by construction.

Ports are fixed (so Playwright's webServer can poll a known URL) but overridable:
    CP_FULLSTACK_IDENTITY_PORT / CP_FULLSTACK_LCR_PORT / CP_FULLSTACK_BROKER_PORT

Run:  python -m tests.fullstack_stack          (stays up; Ctrl+C stops everything)
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import requests

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tests.e2e.conftest import _STRIP_ENV, _serve_in_thread, _wait_http  # noqa: E402

IDENTITY_PORT = int(os.environ.get("CP_FULLSTACK_IDENTITY_PORT", "8921"))
LCR_PORT = int(os.environ.get("CP_FULLSTACK_LCR_PORT", "8922"))
BROKER_PORT = int(os.environ.get("CP_FULLSTACK_BROKER_PORT", "8924"))


class StackError(SystemExit):
    pass


def _load_cp_test_env() -> dict[str, str]:
    """CP_TEST_* from the process env, falling back to the repo .env (dotenv). Values are
    secrets (service key!) — they go into the broker child env only, never into output."""
    from dotenv import dotenv_values

    file_vals = dotenv_values(REPO / ".env")  # {} when the file doesn't exist

    def pick(name: str) -> str:
        return (os.environ.get(name) or file_vals.get(name) or "").strip()

    out = {
        "url": pick("CP_TEST_SUPABASE_URL").rstrip("/"),
        "anon": pick("CP_TEST_SUPABASE_ANON_KEY"),
        "service": pick("CP_TEST_SUPABASE_SERVICE_ROLE_KEY"),
    }
    missing = [n for n, v in (("CP_TEST_SUPABASE_URL", out["url"]),
                              ("CP_TEST_SUPABASE_ANON_KEY", out["anon"]),
                              ("CP_TEST_SUPABASE_SERVICE_ROLE_KEY", out["service"])) if not v]
    if missing:
        raise StackError(
            "REFUSING to start: missing " + ", ".join(missing) +
            " (set them in the repo .env — a dedicated TEST Supabase project, never prod).")
    prod = (os.environ.get("SUPABASE_URL") or file_vals.get("SUPABASE_URL") or "").rstrip("/")
    if prod and out["url"] == prod:
        raise StackError("REFUSING to start: CP_TEST_SUPABASE_URL equals SUPABASE_URL — "
                         "the fullstack lane must never run against production.")
    return out


def _preflight_seed_check(url: str, service_key: str) -> None:
    """The lane asserts against the seeded Testvale fixtures — fail fast (with the fix) when
    the test project isn't seeded, instead of every spec failing on an empty dashboard."""
    h = {"apikey": service_key, "Authorization": f"Bearer {service_key}",
         "Prefer": "count=exact", "Range": "0-0"}

    def count(table: str) -> int:
        r = requests.get(f"{url}/rest/v1/{table}", headers=h, timeout=20)
        cr = r.headers.get("Content-Range", "")
        if r.status_code not in (200, 206) or "/" not in cr:
            raise StackError(f"test project preflight failed: {table} -> {r.status_code} "
                             f"(are the migrations applied? backend.apply against the TEST db)")
        total = cr.rsplit("/", 1)[-1]
        return 0 if total in ("*", "") else int(total)

    members, stakes = count("members"), count("stakes")
    if stakes < 1 or members < 5:
        raise StackError(f"test project not seeded (stakes={stakes}, members={members}) — "
                         "run: python -m tests.seed")
    print(f"[fullstack-stack] test project ok (stakes={stakes}, members={members})")


def main() -> int:
    cp = _load_cp_test_env()
    _preflight_seed_check(cp["url"], cp["service"])

    from cryptography.fernet import Fernet

    from tests.mock_lcr import build_state, create_identity_app, create_lcr_app

    identity_base = f"http://127.0.0.1:{IDENTITY_PORT}"
    lcr_base = f"http://127.0.0.1:{LCR_PORT}"
    broker_base = f"http://127.0.0.1:{BROKER_PORT}"

    state = build_state(identity_base=identity_base, lcr_base=lcr_base)
    servers = [
        _serve_in_thread(create_identity_app(state), IDENTITY_PORT),
        _serve_in_thread(create_lcr_app(state), LCR_PORT),
    ]
    _wait_http(f"{identity_base}/__test/state")
    _wait_http(f"{lcr_base}/__test/state")
    print(f"[fullstack-stack] mock identity: {identity_base}")
    print(f"[fullstack-stack] mock LCR:      {lcr_base}")

    # Broker env: identical to the mock-lane harness, except SUPABASE_* is the REAL test
    # project (no stub). _STRIP_ENV keeps the developer's own GITHUB_TOKEN / RESEND_API_KEY /
    # prod values out of the child — the enroll kickoff and emails must no-op in this lane.
    env = dict(os.environ)
    for key in _STRIP_ENV:
        env.pop(key, None)
    env.update({
        "CP_TEST_MODE": "1",
        "CP_TEST_LCR_BASE": lcr_base,
        "CP_TEST_IDENTITY_BASE": identity_base,
        "SUPABASE_URL": cp["url"],
        "SUPABASE_SERVICE_ROLE_KEY": cp["service"],
        "SUPABASE_ANON_KEY": cp["anon"],
        "LOGIN_EVAL_BUDGET_SECONDS": "30",   # evals answer synchronously (mock LCR is fast)
        "LOGIN_GATE_BUDGET_SECONDS": "20",
        "CP_TOKEN_KEY": Fernet.generate_key().decode("ascii"),
        # A15 passkey ceremony: the web app runs on localhost:5198 (vite, playwright.config.ts),
        # so the WebAuthn RP id/origin must match it — never the production defaults.
        "WEBAUTHN_RP_ID": "localhost",
        "WEBAUTHN_ORIGINS": "http://localhost:5198",
        "PYTHONUNBUFFERED": "1",
    })
    log_path = REPO / "tools" / "output" / "fullstack_broker.log"  # tools/output is gitignored
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = open(log_path, "w", encoding="utf-8")  # noqa: SIM115 — closed on teardown
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.auth_broker.app:app",
         "--host", "127.0.0.1", "--port", str(BROKER_PORT), "--log-level", "info"],
        cwd=str(REPO), env=env, stdout=log_file, stderr=subprocess.STDOUT)
    try:
        _wait_http(f"{broker_base}/health", timeout_s=90, proc=proc, log_path=log_path)
        print(f"[fullstack-stack] REAL broker:   {broker_base}  (log: {log_path})")
        print(f"[fullstack-stack] broker port: {BROKER_PORT}")
        print("[fullstack-stack] ready — supabase = the CP_TEST project (RLS live). Ctrl+C stops.")
        # Stay up: Playwright (or the developer) owns the lifetime. Exit if the broker dies.
        while True:
            code = proc.poll()
            if code is not None:
                print(f"[fullstack-stack] broker exited with {code} — see {log_path}",
                      file=sys.stderr)
                return code or 1
            time.sleep(1)
    except KeyboardInterrupt:
        print("[fullstack-stack] stopping…")
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        log_file.close()
        for server in servers:
            server.should_exit = True


if __name__ == "__main__":
    raise SystemExit(main())
