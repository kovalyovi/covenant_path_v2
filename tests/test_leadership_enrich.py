"""Leadership role-name enrichment doesn't cry "stale action id" on a dead session (2026-06-18 review).

An empty positionType harvest has two causes: a genuinely STALE action id (a real 200 whose shape lost
positionType) OR — far more common in the steady state — a DEAD delegated LCR session (the POST is
401'd / redirected to login). The old code warned "re-capture the action id" for BOTH, a false alarm
that fired twice per run on a dead session. Now only a real 200-with-no-positionType warns; a non-200
is logged at DEBUG.
"""

import logging

from lcr_client import leadership


class _Resp:
    def __init__(self, status_code, text):
        self.status_code = status_code
        self.text = text


class _Http:
    def __init__(self, resp):
        self._resp = resp

    def post(self, *a, **k):
        return self._resp


class _Session:
    def __init__(self, resp):
        self.session = _Http(resp)


class _Client:
    def __init__(self, resp):
        self.session = _Session(resp)


class _Cap(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record):
        self.records.append(record)


def _run(client):
    h = _Cap()
    leadership.logger.addHandler(h)
    old = leadership.logger.level
    leadership.logger.setLevel(logging.DEBUG)
    try:
        rv = leadership.enrich_role_names(client)
    finally:
        leadership.logger.removeHandler(h)
        leadership.logger.setLevel(old)
    return rv, h.records


def test_dead_session_does_not_warn_stale():
    rv, recs = _run(_Client(_Resp(302, "")))  # login redirect, no flight rows
    assert rv == 0
    assert not any("may be stale" in r.getMessage() for r in recs)
    assert any(r.levelno == logging.DEBUG and "session not live" in r.getMessage() for r in recs)


def test_real_stale_action_id_still_warns():
    # a real 200 whose flight rows carry no positionType → genuinely stale action id
    rv, recs = _run(_Client(_Resp(200, '0:{"foo":"bar"}\n1:[1,2,3]')))
    assert rv == 0
    assert any(r.levelno == logging.WARNING and "may be stale" in r.getMessage() for r in recs)
