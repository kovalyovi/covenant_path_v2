"""Ops endpoint-health verdict honesty (2026-06-18 review).

The "Endpoint health (trend)" card used an error-%-only verdict, so dead/deprecated routes and
best-effort endpoints that 401 by design (when the delegated LCR session lapses while the 45-day
Member Tools token carries the sync) all rendered as a scary "hot". The verdict now respects an
endpoint CLASSIFICATION so only LOAD-BEARING endpoints can go red.
"""

from backend.auth_broker import admin


def test_classify_endpoint():
    assert admin._classify_endpoint("/api/umlu/report/member-list") == "dead"
    assert admin._classify_endpoint("/api/report/one-work/progress-record") == "deprecated"
    assert admin._classify_endpoint("/api/report/one-work/details/{id}") == "deprecated"
    assert admin._classify_endpoint("/api/user-context") == "best_effort"
    assert admin._classify_endpoint("/api/dashboard/data") == "best_effort"
    assert admin._classify_endpoint("/mlt/api/orgs") == "load_bearing"
    assert admin._classify_endpoint("/mlt/records/member-profile/{id}") == "load_bearing"
    assert admin._classify_endpoint("/some/unknown/route") == "load_bearing"  # fail loud


def test_endpoint_verdict_does_not_alarm_on_expected_conditions():
    # dead/deprecated routes are probe-only legacy → never alarm, even at 100% error (pre-fix: "hot").
    assert admin._endpoint_verdict("dead", 100.0) == "expected"
    assert admin._endpoint_verdict("deprecated", 45.0) == "expected"
    # best-effort 401-when-session-lapsed → muted 'best_effort', not 'hot' (pre-fix: "hot" at 26.5%).
    assert admin._endpoint_verdict("best_effort", 26.5) == "best_effort"


def test_endpoint_verdict_load_bearing_is_the_real_signal():
    assert admin._endpoint_verdict("load_bearing", 0.0) == "healthy"
    assert admin._endpoint_verdict("load_bearing", 5.0) == "watch"
    assert admin._endpoint_verdict("load_bearing", 25.0) == "hot"
