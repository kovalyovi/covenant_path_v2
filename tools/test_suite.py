"""
Test suite for the covenant-path platform — verifies the pieces and helps
troubleshoot discrepancies between expected and actual behavior.

Two tiers:
  OFFLINE (default, no network): pure logic + crypto round-trips. Always safe to run.
    - token_store: encrypt/decrypt round-trip, save/get/audit/revoke, redaction.
    - report degradation: _feature_allowed, _mark_profile_blocked, _field_coverage.
    - access parsing helpers and okta_login building blocks (no auth).
  LIVE (--live, needs a valid storage_state.json): exercises the real LCR session.
    - access matrix fetch + runner positions + covenant_path_access.
    - okta_login re-mint building blocks (establish_lcr_session / verify) on a copy.
    - delegated_login mint_session round-trip using the CURRENT session as a
      simulated grant (writes to a temp grant store + temp storage_state, never the
      real ones), incl. calling re-verification and revoke kill-switch.

Every result is logged (lcr_client.logging_setup) and persisted to
tools/output/test_report.json for later troubleshooting.

Usage:
  python tools/test_suite.py            # offline only
  python tools/test_suite.py --live     # offline + live (needs a session)
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lcr_client.logging_setup import get_logger  # noqa: E402

logger = get_logger()
OUTPUT = Path(__file__).resolve().parent / "output"
RESULTS: list[dict] = []


def check(name: str, fn) -> bool:
    start = time.time()
    try:
        detail = fn()
        ok, msg = True, (detail if isinstance(detail, str) else "ok")
    except AssertionError as exc:
        ok, msg = False, f"ASSERT: {exc}"
    except Exception as exc:  # noqa: BLE001
        ok, msg = False, f"{type(exc).__name__}: {exc}"
        logger.error("test %s crashed:\n%s", name, traceback.format_exc())
    ms = int((time.time() - start) * 1000)
    RESULTS.append({"name": name, "ok": ok, "msg": msg, "ms": ms})
    logger.info("[%s] %s (%dms) %s", "PASS" if ok else "FAIL", name, ms, "" if ok else f"- {msg}")
    print(f"  [{'PASS' if ok else 'FAIL'}] {name:<34} {'' if ok else '- ' + msg}")
    return ok


# --- OFFLINE -----------------------------------------------------------------

def test_token_store_roundtrip():
    from lcr_client import token_store
    with tempfile.TemporaryDirectory() as d:
        token_store.STORE_PATH = Path(d) / "g.enc"
        token_store.KEY_PATH = Path(d) / ".k"
        grant = {"stake_unit": 999, "stake_name": "Test Stake", "principal": {"name": "X"},
                 "granting_role_ids": [1, 52], "cookies": [{"name": "idx", "value": "SECRET"}],
                 "refresh_token": "RT", "revoked": False, "expires_at": "2099-01-01T00:00:00"}
        token_store.save_grant(grant)
        got = token_store.get_grant(999)
        assert got["cookies"][0]["value"] == "SECRET", "cookie round-trip failed"
        # encrypted on disk: secret must not appear in plaintext
        assert b"SECRET" not in token_store.STORE_PATH.read_bytes(), "secret stored in cleartext!"
        # redaction hides secrets
        red = token_store.list_grants()[0]
        assert "cookies" not in red and red["has_cookies"], "redaction wrong"
        # audit + revoke
        token_store.append_audit(999, "test_event", {"a": 1})
        assert token_store.get_grant(999)["audit"][-1]["event"] == "test_event"
        assert token_store.revoke(999, "because") is True
        assert token_store.get_grant(999)["revoked"] is True
        return "encrypt/decrypt + redaction + audit + revoke ok"


def test_token_store_key_mismatch():
    from cryptography.fernet import Fernet
    from lcr_client import token_store
    with tempfile.TemporaryDirectory() as d:
        token_store.STORE_PATH = Path(d) / "g.enc"
        token_store.KEY_PATH = Path(d) / ".k"
        token_store.save_grant({"stake_unit": 1, "cookies": [], "audit": []})
        token_store.KEY_PATH.write_bytes(Fernet.generate_key())  # rotate key
        try:
            token_store.list_grants()
        except token_store.TokenStoreError:
            return "rotated key correctly rejected old data"
        raise AssertionError("expected TokenStoreError on key mismatch")


def test_report_degradation_helpers():
    from covenant_path import report
    access = {"features": [{"feature": "menu.view.member.profiles", "allowed": False},
                           {"feature": "menu.member.list", "allowed": True}]}
    assert report._feature_allowed(access, "menu.view.member.profiles") is False
    assert report._feature_allowed(access, "menu.member.list") is True
    assert report._feature_allowed(access, "unknown.feature") is True, "unknown should default allow"
    m = report.CovenantPathMember(
        name="t", unit="u", baptism_date=report.NEEDS_PROFILE, birth_date=None, friends="No",
        aaronic_priesthood="N/A", melchizedek_priesthood="N/A", calling="No",
        ministering_brothers_sisters="No", ministering_assignment=report.NEEDS_PROFILE,
        temple_recommend=report.NEEDS_PROFILE, patriarchal_blessing=report.NEEDS_PROFILE,
        living_ordinance="N/A", membership_duration=None, weeks_since_last_attendance=None,
        baptism_goal_date=None, friends_summary=None, sex=None)
    report._mark_profile_blocked(m)
    assert m.baptism_date == report.BLOCKED and m.temple_recommend == report.BLOCKED
    cov = report._field_coverage([{f: report.BLOCKED for f in report._PROFILE_GATED_FIELDS},
                                  {f: "2020" for f in report._PROFILE_GATED_FIELDS}])
    assert cov["baptism_date"] == {"filled": 1, "blocked": 1, "pending": 0}, cov["baptism_date"]
    return "feature gate + blocked-marking + coverage ok"


def test_calling_union_and_neutralize():
    """Calling: the per-member profile (individualCallings) UNIONs with the org-aggregate — a profile
    'Yes' upgrades, a profile 'No' never downgrades a real org 'Yes' (the Terry Stoner sub-org-calling
    fix). And a whole stake of uniform 'No' is neutralized as the stale-action signature."""
    from covenant_path import report

    def mk(calling="No"):
        return report.CovenantPathMember(
            name="t", unit="u", baptism_date="2024", birth_date="1 Jan 1990", friends="No",
            aaronic_priesthood="N/A", melchizedek_priesthood="N/A", calling=calling,
            ministering_brothers_sisters="No", ministering_assignment="No",
            temple_recommend="No", patriarchal_blessing="No", living_ordinance="N/A",
            membership_duration=None, weeks_since_last_attendance=None, baptism_goal_date=None,
            friends_summary=None, sex="F")

    # 1. org-aggregate said "No" (Terry's sub-org calling isn't in it); profile finds it -> "Yes" + name.
    m = mk("No")
    report._apply_profile(m, {"calling": "Yes",
                              "_calling_names": ["Relief Society Service Committee Member"]})
    assert m.calling == "Yes", m.calling
    assert (m.details or {}).get("callings") == ["Relief Society Service Committee Member"], m.details
    # 2. org-aggregate "Yes"; profile action missed (-> "No") must NOT downgrade a real calling.
    m2 = mk("Yes")
    report._apply_profile(m2, {"calling": "No"})
    assert m2.calling == "Yes", "profile 'No' must not downgrade an org 'Yes'"
    # 3. genuine no-calling: both "No" -> "No".
    m3 = mk("No")
    report._apply_profile(m3, {"calling": "No"})
    assert m3.calling == "No", m3.calling
    # 4. neutralizer: a whole cohort uniformly "No" -> sentinel (stale-action signature)…
    rows = [mk("No") for _ in range(25)]
    assert "calling" in report._neutralize_uniform_stale(rows, with_profile=True)
    assert all(r.calling == report.NEEDS_PROFILE for r in rows)
    # …but a single real "Yes" means it's NOT uniform -> don't neutralize.
    rows2 = [mk("No") for _ in range(24)] + [mk("Yes")]
    assert "calling" not in report._neutralize_uniform_stale(rows2, with_profile=True)
    return "calling union + names + neutralize ok"


def test_okta_building_blocks():
    from lcr_client import okta_login
    s = okta_login.session_from_cookies([{"name": "a", "value": "b", "domain": "x.churchofjesuschrist.org"}])
    assert s.cookies.get("a") == "b"
    v, c = okta_login._pkce()
    assert 42 <= len(v) <= 128 and len(c) >= 42, "pkce sizing"
    return "session_from_cookies + pkce ok"


def test_access_humanize():
    from lcr_client import access
    assert access._humanize("menu.temple.recommend.status") == "Temple recommend status"
    assert access._humanize("some.unknown.key") == "Unknown key"
    return "i18n humanize ok"


def test_name_cache_roundtrip():
    from pathlib import Path
    from lcr_client import access
    with tempfile.TemporaryDirectory() as d:
        access.NAME_CACHE_PATH = Path(d) / "role_names.json"
        assert access.register_names({4: "Bishop", 1: "Stake President"}) == 2
        assert access.register_names({4: "Bishop", 52: "Stake Clerk"}) == 1  # only new
        cache = access._load_name_cache()
        assert cache["4"] == "Bishop" and cache["52"] == "Stake Clerk"
        assert access.register_names({99: ""}) == 0  # empty names ignored
        return "register_names merge + persist + ignore-empty ok"


def test_profile_cache():
    from pathlib import Path
    from covenant_path.profile_cache import ProfileCache
    with tempfile.TemporaryDirectory() as d:
        c = ProfileCache(Path(d) / "pc.json", max_age_days=7)
        assert c.get("u1") is None                         # miss (empty)
        c.put("u1", {"baptism_date": "6 Feb 2026", "temple_recommend": "No"})
        got = c.get("u1")
        assert got == {"baptism_date": "6 Feb 2026", "temple_recommend": "No"}, got  # hit, no _ts
        c.save()
        c2 = ProfileCache(Path(d) / "pc.json", max_age_days=7)
        assert c2.get("u1") is not None                    # persisted
        # expiry
        c3 = ProfileCache(Path(d) / "pc.json", max_age_days=0)
        assert c3.get("u1") is None                        # 0-day window -> always stale
        # prune drops members no longer present
        assert c.prune({"u2"}) == 1 and c.get("u1") is None
        return f"hit/miss/persist/expiry/prune ok; stats={c2.stats}"


def test_leadership_harvest():
    from lcr_client import leadership
    objs = [{"orgName": "EQ", "positionType": {"id": 138, "name": "Elders Quorum President"},
             "children": [{"positionType": {"id": 139, "name": "EQ First Counselor"}}]},
            {"positionType": {"id": "bad"}}, {"positionType": {"id": 4, "name": "Bishop"}}]
    pairs = leadership.harvest_role_names(objs)
    assert pairs == {138: "Elders Quorum President", 139: "EQ First Counselor", 4: "Bishop"}, pairs
    return "recursive positionType harvest ok"


def test_sheets_preserve_failed_units():
    from sheets_sync.service import SheetsSync
    m = object.__new__(SheetsSync)  # _merge uses no instance attrs
    existing = {
        "Alice": ["Alice", "Seabrook (Spanish)", "", "", "", "", "Yes"] + [""] * 8 + ["Yes"],
        "Bob": ["Bob", "Bond Park", "", "", "", "", "Yes"] + [""] * 8,
    }
    members = [{"name": "Bob", "unit": "Bond Park", "friends": "Yes"}]  # Alice's unit failed
    rows_no, ch_no = m._merge(members, dict(existing), [], preserve_units=set())
    rows_p, ch_p = m._merge(members, dict(existing), [], preserve_units={"Seabrook (Spanish)"})
    assert sum(c["field"] == "Removed" for c in ch_no) == 1, "Alice should be removed without preserve"
    assert sum(c["field"] == "Removed" for c in ch_p) == 0, "Alice should be kept with preserve"
    assert any(r[0] == "Alice" and r[-1] == "Yes" for r in rows_p), "Alice's manual P col must survive"
    return "failed-unit rows preserved (with manual cols) ok"


def test_clean_missing_filters_unnamed():
    from lcr_client import access
    row = {"label": "Stake leadership", "granting_roles": [
        {"id": 4, "name": "Bishop"}, {"id": 57, "name": "Ward Clerk"},
        {"id": 4, "name": "Bishop"},          # dup
        {"id": 364, "name": "role 364"}, {"id": 55, "name": "role 55"}]}
    out = access._clean_missing(row)
    assert out["granted_by"] == ["Bishop", "Ward Clerk"], out["granted_by"]
    assert out["also_unnamed_roles"] == 2, out["also_unnamed_roles"]
    return "named-only + dedupe + unnamed count ok"


def test_missionary_roster_parse():
    """The /mlt/orgs/missionary flight → assignedToUnit records, with the optional mission filter."""
    from lcr_client.missionaries import fetch_unit_missionaries
    flight = (
        '0:["$","div",null,{}]\n'
        '1:{"assignedToUnit":[{"uuid":"u1","name":"Elder Test","phoneNumber":"+1 555",'
        '"email":"e@missionary.org","missionName":"NC Raleigh Mission","missionId":2011727},'
        '{"uuid":"u2","name":"Sister Other","missionId":9999}],'
        '"servingFromUnit":[],"returnedFromUnit":[]}\n'
    )

    class _R:
        def __init__(self, t):
            self.text = t

    class _Sess:
        def post(self, *a, **k):
            return _R(flight)

    class _Client:
        session = _Sess()

    allm = fetch_unit_missionaries(_Client(), 44911)
    assert len(allm) == 2 and allm[0]["name"] == "Elder Test", allm
    assert allm[0]["mission_id"] == 2011727 and allm[0]["email"] == "e@missionary.org"
    filtered = fetch_unit_missionaries(_Client(), 44911, mission_id=2011727)
    assert len(filtered) == 1 and filtered[0]["uuid"] == "u1", filtered
    return "missionary flight parse + mission filter ok"


def test_email_relay_validation():
    """The auth relay rejects bad input before any network call (no open-relay / enumeration)."""
    from backend.auth_broker import email_relay
    for bad in ("", "nope", "x" * 300 + "@a.com"):
        try:
            email_relay.start_email_login(bad)
            raise AssertionError(f"accepted bad email: {bad[:16]}")
        except email_relay.RelayError:
            pass
    try:
        email_relay.verify_email_login("a@b.com", "")
        raise AssertionError("accepted empty code")
    except email_relay.RelayError:
        pass
    return "email relay rejects bad email + empty code pre-network"


def test_google_oauth_state():
    """M7 OAuth: signed state binds the stake + resists tampering; refresh token vault round-trips."""
    import os as _os
    from cryptography.fernet import Fernet
    _os.environ["CP_TOKEN_KEY"] = Fernet.generate_key().decode()  # self-contained key for the vault
    from backend.auth_broker import google_oauth as g
    st = g.sign_state("stake-xyz-1")
    assert g.verify_state(st) == "stake-xyz-1", "state round-trip"
    for bad in (st[:-2] + "zz", "garbage", st.replace(".", "_")):
        try:
            g.verify_state(bad)
            raise AssertionError(f"tamper not caught: {bad[:12]}")
        except g.OAuthError:
            pass
    enc = g.encrypt_refresh("1//refresh-abc")
    assert g.decrypt_refresh(enc) == "1//refresh-abc", "token vault round-trip"
    assert enc != "1//refresh-abc", "refresh token must be encrypted at rest"
    return "oauth state sign/verify/tamper + encrypted refresh-token vault ok"


# --- LIVE --------------------------------------------------------------------

def test_live_access_matrix():
    from lcr_client import LcrClient
    from lcr_client.access import covenant_path_access, fetch_access_matrix
    client = LcrClient()
    m = fetch_access_matrix(client.session)
    assert len(m.sections) >= 5 and len(m._by_feature) > 50, "matrix too small"
    rep = covenant_path_access(client)
    assert rep["runner_positions"], "no runner positions"
    assert "menu.view.member.profiles" in {r["feature"] for r in rep["features"]}
    return f"{len(m._by_feature)} features; runner can_pull_all={rep['can_pull_all']}"


def test_live_remint_building_blocks():
    """Prove stored Okta cookies -> /api/auth/login -> fresh LCR session works."""
    import json as _json

    from lcr_client import okta_login
    state = _json.loads(Path(okta_login.DEFAULT_STORAGE_STATE).read_text(encoding="utf-8"))
    s = okta_login.session_from_cookies(state["cookies"])
    okta_login.establish_lcr_session(s)
    me = okta_login.verify_session(s)
    assert me.get("name") or me.get("email"), "no identity after re-mint"
    return f"re-mint ok as {me.get('name')}"


def test_live_delegated_roundtrip():
    """Simulate a grant from the CURRENT session, mint from it, verify, revoke.
    Uses TEMP store + TEMP storage_state — never touches the real ones."""
    import json as _json

    from lcr_client import delegated_login, okta_login, token_store
    state = _json.loads(Path(okta_login.DEFAULT_STORAGE_STATE).read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as d:
        token_store.STORE_PATH = Path(d) / "g.enc"
        token_store.KEY_PATH = Path(d) / ".k"
        tmp_state = Path(d) / "storage_state.json"

        # build a grant from the live session
        client = delegated_login._client_from_cookies(state["cookies"])
        access = covenant_path_access_safe(client)
        unit, name = delegated_login._stake_of(access["runner_positions"], None)
        token_store.save_grant({
            "stake_unit": unit, "stake_name": name,
            "principal": {"name": "self-test"}, "granting_role_ids": access["role_ids"],
            "granted_at": "now", "expires_at": "2099-01-01T00:00:00",
            "max_lifetime_days": 1, "consent": True, "consent_text": "test",
            "cookies": state["cookies"], "refresh_token": None,
            "revoked": False, "revoked_at": None, "audit": [],
        })
        info = delegated_login.mint_session(unit, storage_state_path=tmp_state)
        assert info["principal"], "mint returned no principal"
        assert tmp_state.exists(), "mint did not write storage_state"
        # kill switch
        assert delegated_login.revoke(unit, "test-done") is True
        try:
            delegated_login.mint_session(unit, storage_state_path=tmp_state)
        except delegated_login.DelegationError:
            return f"mint as {info['principal']} (roles {info['role_ids']}); revoke blocks re-mint"
        raise AssertionError("revoked grant should refuse minting")


def covenant_path_access_safe(client):
    from lcr_client.access import covenant_path_access
    return covenant_path_access(client)


# --- runner ------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="covenant-path test suite")
    ap.add_argument("--live", action="store_true", help="also run tests needing a live LCR session")
    args = ap.parse_args()

    print("== OFFLINE tests ==")
    offline = [test_token_store_roundtrip, test_token_store_key_mismatch,
               test_report_degradation_helpers, test_calling_union_and_neutralize,
               test_okta_building_blocks, test_access_humanize,
               test_name_cache_roundtrip, test_clean_missing_filters_unnamed,
               test_leadership_harvest, test_profile_cache, test_sheets_preserve_failed_units,
               test_missionary_roster_parse, test_email_relay_validation, test_google_oauth_state]
    for t in offline:
        check(t.__name__, t)

    if args.live:
        print("\n== LIVE tests (need storage_state.json) ==")
        for t in (test_live_access_matrix, test_live_remint_building_blocks,
                  test_live_delegated_roundtrip):
            check(t.__name__, t)

    passed = sum(1 for r in RESULTS if r["ok"])
    report = {"generated": time.strftime("%Y-%m-%dT%H:%M:%S"), "live": args.live,
              "passed": passed, "total": len(RESULTS), "results": RESULTS}
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "test_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\n== {passed}/{len(RESULTS)} passed == -> tools/output/test_report.json")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
