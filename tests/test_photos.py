"""Regression for the 2026-06-18 CI exit-1 bug.

The avatar/photo pass is best-effort — scripts/daily_sync.py wraps it in `except Exception` ("never
fail the data sync over avatars"). backend.photos._sb() used to `raise SystemExit` when the Supabase
service-role key was missing; SystemExit is a BaseException, so it slipped past that guard and exited
the whole sync with code 1 (after the data had already synced). It must raise a normal, catchable
Exception so the guard can swallow it.
"""

import pytest

from backend import photos


def test_sb_missing_env_raises_catchable_exception(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    # Must be a normal Exception (caught by `except Exception`), never SystemExit/BaseException.
    with pytest.raises(RuntimeError):
        photos._sb()


def test_sb_error_is_not_a_baseexception_only(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    try:
        photos._sb()
    except Exception as exc:  # noqa: BLE001 — the whole point is that `except Exception` catches it
        assert not isinstance(exc, SystemExit)
        assert isinstance(exc, Exception)
    else:  # pragma: no cover
        pytest.fail("_sb() did not raise with the env unset")
