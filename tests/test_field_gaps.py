"""Degraded-bulk-payload alarm (2026-06-18 review).

A field that CAN be rescued from /api/v5/sync (temple_recommend, living_ordinance, calling, …) showing
100% missing across a populated stake is the signature of a PARTIAL bulk payload (a dropped household
directory / templeRecommendStatus sub-tree), not a dead LCR session (which only blocks profile-only
fields like patriarchal). _emit_field_gap_report now raises a distinct error-level alarm + a
`degraded_payload_fields` stats key for exactly that case, so a gutted payload is detected instead of
silently degrading the whole stake to sentinels.
"""

import logging

from covenant_path import report as R


class _M:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


def _full(**override):
    """A member with every sentinel-able field FILLED, then the given override(s)."""
    base = {f: "Yes" for f in (*R._BULK_RESCUED_FIELDS, *R._PROFILE_ONLY_FIELDS)}
    base.update(override)
    return _M(**base)


class _Cap(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record):
        self.records.append(record)


def _emit(rows, stats):
    """Run _emit_field_gap_report capturing report.py's own logger (robust to propagation config)."""
    h = _Cap()
    R.logger.addHandler(h)
    old = R.logger.level
    R.logger.setLevel(logging.DEBUG)
    try:
        R._emit_field_gap_report(rows, stats, can_profiles=True, stake=503991)
    finally:
        R.logger.removeHandler(h)
        R.logger.setLevel(old)
    return h.records


def test_degraded_payload_flagged_when_whole_rescuable_field_100pct_missing():
    rows = [_full(temple_recommend=R.NEEDS_PROFILE) for _ in range(25)]
    stats = {"profile_ok": 1}  # profile merge ran → this is NOT a dead-session attribution
    recs = _emit(rows, stats)
    assert stats.get("degraded_payload_fields") == ["temple_recommend"]
    assert any(r.levelno >= logging.ERROR and "DEGRADED /api/v5/sync" in r.getMessage() for r in recs)


def test_no_degraded_alarm_for_partial_or_small_stake():
    # a PARTIAL gap (12 of 25) is a normal directory miss, not a gutted payload → no alarm
    rows = [_full(temple_recommend=R.NEEDS_PROFILE) for _ in range(12)] + [_full() for _ in range(13)]
    stats = {"profile_ok": 1}
    _emit(rows, stats)
    assert "degraded_payload_fields" not in stats
    # a SMALL stake (<20 members) all-missing could be a tiny branch, not a degraded payload → no alarm
    stats2 = {"profile_ok": 1}
    _emit([_full(temple_recommend=R.NEEDS_PROFILE) for _ in range(10)], stats2)
    assert "degraded_payload_fields" not in stats2


def test_patriarchal_only_gap_is_not_a_degraded_payload():
    # patriarchal_blessing is PROFILE-only (dead-session, re-auth) — 100% missing must NOT trip the
    # bulk-payload alarm (it is not in _BULK_RESCUED_FIELDS).
    stats = {"profile_ok": 0}  # dead session
    _emit([_full(patriarchal_blessing=R.NEEDS_PROFILE) for _ in range(25)], stats)
    assert "degraded_payload_fields" not in stats
