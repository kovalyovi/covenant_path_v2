"""
The "I signed in with a different email" claim flow (0065).

These are the SECURITY properties, not just the happy path — the whole feature is a way to hand out
access, so the tests assert what it must REFUSE:

  * the secret goes only to the address already on record, never to the requester
  * an unmatched name and an ambiguous name are indistinguishable in the reply (no enumeration)
  * a link is single-use, expiring, and bound to the sign-in that requested it
  * the grant CLONES the matched leader's rows and can never exceed them

FAILS pre-fix: backend.auth_broker.claim did not exist.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

import pytest

from backend.auth_broker import claim


# --- name matching (pure) -------------------------------------------------------------------------

@pytest.mark.parametrize("roster,first,last,ok", [
    ("Hunsaker, Reed Garrett", "Reed", "Hunsaker", True),
    ("Hunsaker, Reed Garrett", "Garrett", "Hunsaker", True),    # goes by their middle name
    ("Hunsaker, Reed Garrett", "reed", "HUNSAKER", True),       # case-insensitive
    ("Sanhueza, Pedro Alex", "Alex", "Sanhueza", True),
    ("O'Brien, Sean", "Sean", "OBrien", True),                  # punctuation-insensitive
    ("Sanchez, Jose", "Jose", "Sanchez", True),
    ("Hunsaker, Reed Garrett", "Reed", "Hunsakerson", False),   # surname must match exactly
    ("Hunsaker, Reed Garrett", "Reeder", "Hunsaker", False),    # given name is not a prefix match
    ("Hunsaker, Reed Garrett", "", "Hunsaker", False),          # never surname alone
    ("Reed Hunsaker", "Reed", "Hunsaker", False),               # unexpected shape -> no match
    (None, "Reed", "Hunsaker", False),
])
def test_name_matching(roster, first, last, ok):
    assert claim.name_matches(roster, first, last) is ok


def test_accented_roster_names_match_their_plain_spelling():
    assert claim.name_matches("Sánchez, José", "Jose", "Sanchez") is True


def test_mask_email_hides_the_address():
    m = claim.mask_email("reed.hunsaker@gmail.com")
    assert m.startswith("re") and m.endswith(".com")
    assert "hunsaker" not in m and "gmail" not in m


# --- the flow (stubbed REST) ----------------------------------------------------------------------

UNITS = [{"name": "Seabrook Branch (Spanish)", "staffing": [
    {"person": "Hunsaker, Reed Garrett", "person_uuid": "reed"},
    {"person": "Hunsaker, Reed Garrett", "person_uuid": "reed"},   # 2nd calling, SAME person
    {"person": "Nobody, Has No Role", "person_uuid": "norole"},
    {"person": "Twin, Same Name", "person_uuid": "twin-a"},
    {"person": "Twin, Same Name", "person_uuid": "twin-b"},
]}]

ROLES = {
    "reed": [{"id": 1, "stake_id": "s1", "unit_id": "u1", "role": "ward_leader",
              "email": "reed.on.record@example.org", "calling_name": "Elders Quorum President"}],
    "twin-a": [{"id": 2, "stake_id": "s1", "unit_id": "u1", "role": "ward_leader",
                "email": "a@example.org", "calling_name": "Bishop"}],
    "twin-b": [{"id": 3, "stake_id": "s1", "unit_id": "u2", "role": "ward_leader",
                "email": "b@example.org", "calling_name": "Bishop"}],
    "norole": [],
}


class _Ok:
    status_code = 200
    text = ""

    def json(self):
        return []


@pytest.fixture()
def stub(monkeypatch):
    """Stub every REST call so the flow runs offline. `state` records what it tried to do."""
    state = {"claims": [], "sent": [], "granted": [], "patched": []}

    def _rows(table, params):
        if table == "units":
            return UNITS
        if table == "user_roles":
            uuid_ = (params.get("lcr_person_uuid") or "").removeprefix("eq.")
            return ROLES.get(uuid_, [])
        if table == "church_identities":
            return []
        if table == "role_claims":
            if "token_hash" in params:
                want = params["token_hash"].removeprefix("eq.")
                return [c for c in state["claims"] if c.get("token_hash") == want]
            return []                       # rate-limit probe: no recent attempts
        return []

    def _insert(table, body, returning=True):
        row = {"id": len(state["claims"]) + 1, **body}
        state["claims"].append(row)
        return row

    def _patch(table, params, body):
        state["patched"].append(body)
        cid = int((params.get("id") or "eq.0").removeprefix("eq."))
        for c in state["claims"]:
            if c["id"] == cid:
                c.update(body)

    def _post(*a, **k):
        state["granted"].append(k.get("json"))
        return _Ok()

    monkeypatch.setattr(claim, "_rows", _rows)
    monkeypatch.setattr(claim, "_insert", _insert)
    monkeypatch.setattr(claim, "_patch", _patch)
    monkeypatch.setattr(claim.admin, "_send_email",
                        lambda to, subject, html: state["sent"].append((to, subject, html)))
    monkeypatch.setattr(claim.requests, "post", _post)
    monkeypatch.setattr(claim, "SUPABASE_URL", "https://x")
    monkeypatch.setattr(claim, "SERVICE_KEY", "k")
    return state


def _token_from(stub) -> str:
    link = stub["sent"][-1][2]
    return link.split("token=")[1].split('"')[0]


def test_the_link_goes_to_the_address_on_record_never_the_requester(stub):
    out = claim.start_claim("attacker@evil.example", "Reed", "Hunsaker")
    assert out["status"] == "sent"
    # THE core property: mailed to the on-record address, not to whoever asked.
    assert stub["sent"][0][0] == "reed.on.record@example.org"
    # ...and the reply only ever hands back a mask.
    assert "reed.on.record" not in out["hint"]
    # The email names who is asking, so the real owner can refuse.
    assert "attacker@evil.example" in stub["sent"][0][2]


def test_token_is_stored_hashed_only(stub):
    claim.start_claim("someone@example.org", "Reed", "Hunsaker")
    row = stub["claims"][-1]
    token = _token_from(stub)
    assert row["token_hash"] == hashlib.sha256(token.encode()).hexdigest()
    assert token not in str(row)          # the raw token is never persisted


def test_unmatched_and_ambiguous_names_are_indistinguishable(stub):
    nobody = claim.start_claim("x@example.org", "Nosuch", "Person")
    ambiguous = claim.start_claim("x@example.org", "Same", "Twin")
    assert nobody == ambiguous == {"status": "no_match"}
    assert stub["sent"] == []             # nothing mailed in either case


def test_a_leader_with_no_role_is_not_claimable(stub):
    assert claim.start_claim("x@example.org", "Has", "Nobody")["status"] == "no_match"


def test_rate_limited_per_claimant(stub, monkeypatch):
    monkeypatch.setattr(claim, "_recent_attempts", lambda c: claim.MAX_ATTEMPTS_PER_DAY)
    with pytest.raises(claim.ClaimError, match="Too many attempts"):
        claim.start_claim("x@example.org", "Reed", "Hunsaker")
    assert stub["sent"] == []


def test_every_attempt_is_audited_even_when_unmatched(stub):
    claim.start_claim("x@example.org", "Nosuch", "Person")
    assert stub["claims"][-1]["status"] == "no_match"
    assert stub["claims"][-1]["claimant_email"] == "x@example.org"


def test_completing_the_claim_clones_exactly_the_matched_roles(stub):
    claim.start_claim("newmail@example.org", "Reed", "Hunsaker")
    out = claim.complete_claim(_token_from(stub), "newmail@example.org")
    assert out["status"] == "linked" and out["granted"] == 1
    grant = stub["granted"][0]
    src = ROLES["reed"][0]
    # Same stake, same unit, same role — never more.
    assert (grant["stake_id"], grant["unit_id"], grant["role"]) == \
           (src["stake_id"], src["unit_id"], src["role"])
    assert grant["email"] == "newmail@example.org"
    # Keyed by email with NO person uuid, so provision_roles + the 0063 triggers leave it alone.
    assert "lcr_person_uuid" not in grant and grant["source"] == "claim"


def test_a_link_cannot_be_used_by_a_different_sign_in(stub):
    claim.start_claim("requester@example.org", "Reed", "Hunsaker")
    with pytest.raises(claim.ClaimError, match="Sign in with the address"):
        claim.complete_claim(_token_from(stub), "someone.else@example.org")
    assert stub["granted"] == []


def test_a_link_is_single_use(stub):
    claim.start_claim("newmail@example.org", "Reed", "Hunsaker")
    tok = _token_from(stub)
    claim.complete_claim(tok, "newmail@example.org")
    # The token hash is burned on consume, so the second attempt can't even find the row.
    with pytest.raises(claim.ClaimError, match="isn't valid"):
        claim.complete_claim(tok, "newmail@example.org")


def test_an_expired_link_is_refused(stub):
    claim.start_claim("newmail@example.org", "Reed", "Hunsaker")
    stub["claims"][-1]["expires_at"] = (
        datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    with pytest.raises(claim.ClaimError, match="expired"):
        claim.complete_claim(_token_from(stub), "newmail@example.org")
    assert stub["granted"] == []


def test_a_bogus_token_is_refused(stub):
    with pytest.raises(claim.ClaimError, match="isn't valid"):
        claim.complete_claim("not-a-real-token", "x@example.org")


def test_claiming_your_own_recorded_address_short_circuits(stub):
    out = claim.start_claim("reed.on.record@example.org", "Reed", "Hunsaker")
    assert out["status"] == "already_on_record"
    assert stub["sent"] == []             # no pointless email to yourself


def test_short_names_are_rejected_before_any_lookup(stub):
    with pytest.raises(claim.ClaimError, match="first and last name"):
        claim.start_claim("x@example.org", "R", "H")
    assert stub["claims"] == []
