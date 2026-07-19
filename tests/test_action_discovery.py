"""
Offline tests for HTTP action-id discovery (lcr_client.action_discovery.discover_http) — no network.

Regression for the 2026-07 LCR Turbopack rebuild: every /mlt server-action id rotated AND the old
Playwright self-heal couldn't run where it mattered (no playwright on the broker; headless operator
login MFA-blocked) — so patriarchal/calling/ministering/recommend gap-fills silently 404'd for
weeks (profile_action 60222763 "permanent failure" on every member, `resolved: []` heals).
discover_http harvests the build's chunk graph over pure HTTP with the caller's LIVE session and
maps the createServerReference("<id>", …, "<name>") registrations by NAME, verifying the record
canary by POST before persisting.

Run: python -m pytest tests/test_action_discovery.py -q
"""

from __future__ import annotations

import json

from lcr_client import action_discovery
from lcr_client.action_discovery import (
    _chunk_refs,
    _server_refs,
    _targets_from_names,
    discover_http,
)

# Realistic minified registration snippet (shape captured live 2026-07-19). The name string is the
# 5th argument and survives minification — it's the stable key across redeploys.
MINIFIED_JS = (
    'let tq=(0,tz.createServerReference)("40fc7ba5e4db8902cb311982ed730f4447d2b34b64",'
    'tz.callServer,void 0,tz.findSourceMapURL,"getLanguages"),'
    'td=(0,tz.createServerReference)("60d3d432376be6002cbd1e050593b164c082a0f184",'
    'tz.callServer,void 0,tz.findSourceMapURL,"getMemberData"),'
    'tr=(0,tz.createServerReference)("60858689751bc52d895ca386437992b6a4970a484d",'
    'tz.callServer,void 0,tz.findSourceMapURL,"getRecommendData"),'
    'tm=(0,tz.createServerReference)("608c0018605ee18d7f2a2fc077a73c2bde17fedb6d",'
    'tz.callServer,void 0,tz.findSourceMapURL,"getMinisteringData"),'
    'tc=(0,tz.createServerReference)("605bf78aabb9282ce1dc2b30f708a5192763c935a4",'
    'tz.callServer,void 0,tz.findSourceMapURL,"getCallingsAndClassesData")'
)


def test_server_refs_parse_minified_registrations():
    refs = _server_refs(MINIFIED_JS)
    assert refs["getMemberData"] == "60d3d432376be6002cbd1e050593b164c082a0f184"
    assert refs["getRecommendData"] == "60858689751bc52d895ca386437992b6a4970a484d"
    assert len(refs) == 5


def test_chunk_refs_catch_script_srcs_and_escaped_flight_refs():
    # Turbopack filenames include dots/tildes/dashes; inline flight rows escape "/" as /.
    # Both shapes MUST be harvested — missing the escaped ones is exactly how the old harvest went
    # blind (the chunk defining the data getters was only referenced from the flight rows).
    html = (
        '<script src="/mlt/_next/static/chunks/0-6ps7.dy--~w.js"></script>'
        '<script src="/mlt/_next/static/chunks/turbopack-085~j9y3blc91.js"></script>'
        'self.__next_f.push([1,"1:I[339756,[\\"\\u002Fmlt\\u002F_next\\u002F'
        'static\\u002Fchunks\\u002F0u4hw02053gi_.js\\"],\\"default\\"]"])'
    )
    refs = _chunk_refs(html)
    assert "static/chunks/0-6ps7.dy--~w.js" in refs
    assert "static/chunks/turbopack-085~j9y3blc91.js" in refs
    assert "static/chunks/0u4hw02053gi_.js" in refs


def test_targets_from_names_maps_current_and_legacy_names():
    named = {
        "getMemberData": "aa" * 21, "getRecommendData": "bb" * 21,
        "getMinisteringData": "cc" * 21, "getCallingsAndClassesData": "dd" * 21,
        "getUnitOrgWrapper": "ee" * 21, "getFullTimeMissionaryWrapper": "ff" * 21,
        "getLanguages": "99" * 21,  # unrelated actions are ignored
    }
    out = _targets_from_names(named)
    assert out == {"record": "aa" * 21, "recommend": "bb" * 21, "ministering": "cc" * 21,
                   "callings": "dd" * 21, "leadership": "ee" * 21, "missionary": "ff" * 21}
    # a build that reverts to an older name still maps (fallback name list)
    assert _targets_from_names({"getMemberProfile": "ab" * 21}) == {"record": "ab" * 21}


class _FakeResp:
    def __init__(self, status_code: int, text: str):
        self.status_code = status_code
        self.text = text


class _FakeHttp:
    """requests.Session stand-in: URL suffix -> response text."""

    def __init__(self, pages: dict[str, tuple[int, str]]):
        self.pages = pages

    def get(self, url, **kw):
        for suffix, (code, text) in self.pages.items():
            if suffix in url:
                return _FakeResp(code, text)
        return _FakeResp(404, "")


class _FakeSession:
    def __init__(self, pages):
        self.session = _FakeHttp(pages)


def test_discover_http_maps_names_and_verifies_record(monkeypatch):
    uuid = "5c3fb668-f0a8-4452-8704-0a1374911aeb"
    pages = {
        f"member-profile/{uuid}": (200, '<script src="/mlt/_next/static/chunks/0abc.js"></script>'),
        "/mlt/orgs": (200, ""),  # orgs harvest is best-effort; empty here
        "static/chunks/0abc.js": (200, MINIFIED_JS),
    }
    calls = []

    def fake_call_action(session, person_uuid, action_id, args):
        calls.append(action_id)
        record = {"uuid": person_uuid, "ordinances": [], "hasPatriarchalBlessing": True}
        return [record]  # the record detector matches -> canary verified

    monkeypatch.setattr("lcr_client.member_profile.call_action", fake_call_action)
    found = discover_http(_FakeSession(pages), uuid)
    assert found["record"] == "60d3d432376be6002cbd1e050593b164c082a0f184"
    assert found["callings"] == "605bf78aabb9282ce1dc2b30f708a5192763c935a4"
    # exactly ONE verify POST (the record canary) — not a probe of every harvested id
    assert calls == ["60d3d432376be6002cbd1e050593b164c082a0f184"]


def test_discover_http_discards_set_when_record_verify_fails(monkeypatch):
    uuid = "5c3fb668-f0a8-4452-8704-0a1374911aeb"
    pages = {
        f"member-profile/{uuid}": (200, '<script src="/mlt/_next/static/chunks/0abc.js"></script>'),
        "/mlt/orgs": (200, ""),
        "static/chunks/0abc.js": (200, MINIFIED_JS),
    }
    monkeypatch.setattr("lcr_client.member_profile.call_action",
                        lambda *a, **k: [{"error": "Forbidden"}])  # shape verify misses
    assert discover_http(_FakeSession(pages), uuid) == {}


def test_discover_http_shape_probe_fallback_when_names_rotate(monkeypatch):
    # A future build that renames the getters: name map finds no record -> every harvested id is
    # shape-probed against the detectors instead.
    uuid = "5c3fb668-f0a8-4452-8704-0a1374911aeb"
    renamed = MINIFIED_JS.replace("getMemberData", "loadPersonRecord")
    pages = {
        f"member-profile/{uuid}": (200, '<script src="/mlt/_next/static/chunks/0abc.js"></script>'),
        "/mlt/orgs": (200, ""),
        "static/chunks/0abc.js": (200, renamed),
    }

    def fake_call_action(session, person_uuid, action_id, args):
        if action_id == "60d3d432376be6002cbd1e050593b164c082a0f184":
            return [{"uuid": person_uuid, "ordinances": []}]
        return [{}]

    monkeypatch.setattr("lcr_client.member_profile.call_action", fake_call_action)
    found = discover_http(_FakeSession(pages), uuid)
    assert found["record"] == "60d3d432376be6002cbd1e050593b164c082a0f184"
    # the name-mapped non-record targets still land via their unchanged names
    assert found["recommend"] == "60858689751bc52d895ca386437992b6a4970a484d"


def test_discover_http_raises_on_dead_session():
    # A dead session's page GET is a redirect (302/307), not 200 — discovery must raise so heal()
    # can fall back (and the broker's needs_reauth probe stays honest), never persist garbage.
    uuid = "5c3fb668-f0a8-4452-8704-0a1374911aeb"
    pages = {f"member-profile/{uuid}": (302, "")}
    try:
        discover_http(_FakeSession(pages), uuid)
        raise AssertionError("expected RuntimeError on non-200 page GET")
    except RuntimeError as exc:
        assert "session" in str(exc)


def test_heal_persists_http_discovery(monkeypatch, tmp_path):
    # heal() must prefer the HTTP lane and persist with method="http" (the Playwright lane would
    # crash on the broker — the exact failure that left the ids stale for weeks).
    saved = {}
    monkeypatch.setattr(action_discovery.action_config, "save",
                        lambda actions, meta=None: saved.update({"actions": actions, "meta": meta}))
    monkeypatch.setattr(action_discovery, "discover_http",
                        lambda session, uuid: {"record": "aa" * 21, "callings": "bb" * 21})
    monkeypatch.setattr(action_discovery, "PROFILE_CACHE", tmp_path / "profile_cache.json")

    class _S:
        def reload(self):
            pass

    ids = action_discovery.heal(_S(), "some-uuid")
    assert ids["record"] == "aa" * 21
    assert saved["meta"]["method"] == "http"
    assert "record" in saved["meta"]["resolved"]


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
