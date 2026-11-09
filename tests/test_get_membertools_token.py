"""
Offline tests for scripts/get_membertools_token.py (D85) — no network, no DB.

The pull-stake-data CI workflow loads the stored Member Tools refresh token
from the same store the daily sync uses (Supabase first, local file store as
a fallback) so pull_stake_data.py can renew its bearer without a headless
Okta login (HTTP 428). The script must:
- return the Supabase token when one is stored (never consult anything else);
- fall back to the file store when Supabase is empty;
- return None (exit 1) when no token is stored anywhere — never raise, so
  the workflow can fall back to the Okta login instead of failing;
- print ONLY the token to stdout (callers capture it; a secret must never
  share stdout with log lines).

Run: python -m pytest tests/test_get_membertools_token.py -q
"""

from __future__ import annotations

import sys
import types

import scripts.get_membertools_token as gmt


class _FakeConn:
    def close(self):
        pass


def _install(monkeypatch, *, db_token=None, db_raises=False, file_token=None):
    """Fake backend.credentials/db + lcr_client.token_store in sys.modules."""
    backend_pkg = types.ModuleType("backend")
    creds = types.ModuleType("backend.credentials")
    dbmod = types.ModuleType("backend.db")

    def _connect():
        if db_raises:
            raise RuntimeError("DB down")
        return _FakeConn()

    def _stake_id_for_unit(conn, unit):
        return "stake-uuid-1"

    def _get_refresh(conn, sid):
        if db_token is None:
            return None
        return {"refresh_token": db_token, "minted_at": "2026-11-01"}

    creds.stake_id_for_unit = _stake_id_for_unit
    creds.get_membertools_refresh = _get_refresh
    dbmod.connect = _connect

    lcr_pkg = types.ModuleType("lcr_client")
    tstore = types.ModuleType("lcr_client.token_store")
    tstore.get_membertools_token = lambda unit: (
        {"refresh_token": file_token} if file_token else {}
    )

    monkeypatch.setitem(sys.modules, "backend", backend_pkg)
    monkeypatch.setitem(sys.modules, "backend.credentials", creds)
    monkeypatch.setitem(sys.modules, "backend.db", dbmod)
    monkeypatch.setitem(sys.modules, "lcr_client", lcr_pkg)
    monkeypatch.setitem(sys.modules, "lcr_client.token_store", tstore)


def test_supabase_token_returned(monkeypatch):
    _install(monkeypatch, db_token="tok-supabase", file_token="tok-file")
    assert gmt.get_token(503991) == "tok-supabase"


def test_falls_back_to_file_store_when_supabase_empty(monkeypatch):
    _install(monkeypatch, db_token=None, file_token="tok-file")
    assert gmt.get_token(503991) == "tok-file"


def test_none_when_no_token_anywhere(monkeypatch):
    _install(monkeypatch, db_token=None, file_token=None)
    assert gmt.get_token(503991) is None


def test_db_error_falls_back_to_file_store_without_raising(monkeypatch):
    _install(monkeypatch, db_raises=True, file_token="tok-file")
    assert gmt.get_token(503991) == "tok-file"


def test_db_error_and_empty_file_store_returns_none(monkeypatch):
    _install(monkeypatch, db_raises=True, file_token=None)
    assert gmt.get_token(503991) is None


def test_main_prints_only_the_token(monkeypatch, capsys):
    _install(monkeypatch, db_token="tok-supabase")
    assert gmt.main(["--stake", "503991"]) == 0
    assert capsys.readouterr().out == "tok-supabase\n"


def test_main_exits_1_with_no_token(monkeypatch, capsys):
    _install(monkeypatch, db_token=None, file_token=None)
    assert gmt.main([]) == 1
    assert capsys.readouterr().out == ""
