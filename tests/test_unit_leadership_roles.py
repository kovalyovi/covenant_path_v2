# Regression for "an Elders Quorum President signs in and sees NOTHING" (2026-08-05, Reed Hunsaker,
# Seabrook Branch (Spanish); same for Justin Fawson / Cary 1st Ward, and for the RS / Primary / Young
# Women / Sunday School presidents of both units).
#
# Root cause: provision_roles built ward_leader rows ONLY from `/mlt/api/orgs`, which returns the
# ward's own organization tree (bishopric, clerks, executive secretaries, ward missionaries, temple &
# family history) and NOT the auxiliary presidencies. Those leaders therefore had no user_roles row,
# so RLS returned nothing and login_audit recorded role_scope='none' even though the login itself was
# authorized. `units.staffing` (the Member Tools bulk directory) HAS them, so it is now a second
# source, gated by calling name.
#
# These tests FAIL against the pre-fix code: calling_is_unit_leadership did not exist, and
# provision_roles took no staffing argument.

import pytest

from backend.roles import _staffing_positions, calling_is_unit_leadership


# --------------------------------------------------------------------------------------------------
# The calling gate itself.

@pytest.mark.parametrize("calling", [
    # the bug report
    "Elders Quorum President",
    "Relief Society President",
    "Primary President",
    "Young Women President",
    "Sunday School President",
    # counselors + secretaries ride the same org prefixes
    "Elders Quorum First Counselor",
    "Relief Society Second Counselor",
    "Young Men President",
    "Primary Secretary",
    # presiding council — ward AND branch spellings
    "Bishop",
    "Bishopric First Counselor",
    "Branch President",
    "Branch Presidency Second Counselor",
    # records stewardship
    "Ward Clerk", "Ward Assistant Clerk", "Ward Executive Secretary",
    "Branch Clerk", "Branch Assistant Executive Secretary",
    # missionary work — explicitly in scope (user directive 2026-08-08)
    "Ward Mission Leader", "Assistant Ward Mission Leader", "Ward Missionary",
    "Branch Mission Leader", "Assistant Branch Mission Leader", "Branch Missionary",
    "Ward Temple and Family History Leader",
])
def test_unit_leadership_is_granted(calling):
    assert calling_is_unit_leadership(calling) is True


@pytest.mark.parametrize("calling", [
    # Youth quorum + class presidencies: 12-17-year-olds. LCR withholds the progress record from them
    # and they have no stewardship over the ward's new-member data.
    "Deacons Quorum President",
    "Teachers Quorum First Counselor",
    "Priests Quorum President",
    "Builders of Faith Class President",
    "Gatherers of Light Class First Counselor",
    "Messengers of Hope Class Presidency",
    # support callings, not stewardship
    "Young Women Class Adviser",
    "Deacons Quorum Specialist",
    "Primary Music Leader",
    # not a leadership calling at all
    "",
    None,
    "Assistant Ward Organist",
])
def test_non_stewardship_callings_are_not_granted(calling):
    assert calling_is_unit_leadership(calling) is False


def test_priests_quorum_president_is_excluded_but_the_bishop_still_gets_in():
    # A bishop is listed twice in the staffing roster — as Bishop and as Priests Quorum President.
    # Excluding the youth calling must not cost him access; his "Bishop" row grants it.
    assert calling_is_unit_leadership("Priests Quorum President") is False
    assert calling_is_unit_leadership("Bishop") is True


# --------------------------------------------------------------------------------------------------
# The staffing -> position adapter.

def test_staffing_rows_become_positions_without_a_role_id():
    rows = [
        {"person": "Hunsaker, Reed", "position": "Elders Quorum President",
         "person_uuid": "f8e81fd1", "set_apart": True},
        {"person": "Nobody", "position": "Relief Society President"},   # no uuid -> dropped
        {"person": "Ghost", "person_uuid": "abc"},                      # no calling -> dropped
        "not-a-dict",
    ]
    out = _staffing_positions(rows)
    assert out == [{"person_uuid": "f8e81fd1", "name": "Hunsaker, Reed", "unit_name": None,
                    "role_id": None, "calling": "Elders Quorum President"}]


def test_staffing_adapter_tolerates_empty_input():
    assert _staffing_positions(None) == []
    assert _staffing_positions([]) == []


# --------------------------------------------------------------------------------------------------
# provision_roles: the two ward sources are UNIONed.

class _Unit:
    def __init__(self, number, name, type_):
        self.unit_number, self.name, self.type = number, name, type_


class _Ctx:
    unit_number = 503991
    unit_name = "Test Stake"

    def __init__(self, children):
        self.child_units = children


class _Client:
    """Minimal LcrClient stand-in. `org_callings` returns the INCOMPLETE ward org tree that caused
    the bug — bishopric + clerk only, no auxiliary presidencies."""

    def __init__(self, children, org_positions):
        self._ctx = _Ctx(children)
        self._org = org_positions
        self.session = object()

    def user_context(self):
        return self._ctx

    def org_callings(self, unit_number):
        return {"unitOrgs": [{"positions": self._org.get(unit_number, [])}]}


def _pos(uuid_, name, role_id, calling):
    return {"person": {"uuid": uuid_, "name": name, "currentUnitName": "U"},
            "positionType": {"id": role_id, "name": calling},
            "positionStatus": "ACTIVE_POSITION"}


@pytest.fixture()
def patched(monkeypatch):
    """Stub the LCR access matrix + the DB so provision_roles runs offline."""
    import backend.roles as roles

    class _Matrix:
        def feature_roles(self, feature):
            # Only the bishopric/clerk role ids are 'granted' here — the auxiliary presidencies must
            # get in through the STAFFING lane, not this one.
            return [4, 57]

    monkeypatch.setattr(roles, "fetch_access_matrix", lambda session: _Matrix())
    monkeypatch.setattr(roles, "_email_by_uuid", lambda client: {})
    monkeypatch.setattr(roles, "_load_overrides", lambda conn: [])
    monkeypatch.setattr(roles, "_audit_access", lambda *a, **k: None)
    return roles


class _Cur:
    """Captures the rows provision_roles upserts."""

    def __init__(self, sink):
        self.sink = sink

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        if "insert into user_roles" in sql:
            self.sink.append(params)
        self._last = sql

    def fetchall(self):
        return []

    @property
    def rowcount(self):
        return 0


class _Conn:
    def __init__(self):
        self.rows = []

    def cursor(self):
        return _Cur(self.rows)

    def commit(self):
        pass


def test_auxiliary_presidents_are_provisioned_from_staffing(patched):
    """The exact Seabrook shape: org_callings returns only the branch presidency + clerk, while the
    Member Tools staffing roster also lists the EQ / RS / Sunday School presidents."""
    units = [_Unit(458821, "Seabrook Branch (Spanish)", "BRANCH")]
    org = {458821: [_pos("branch-pres", "Fonseca, Axel", 4, "Branch President"),
                    _pos("clerk", "Someone, Else", 57, "Branch Clerk")]}
    staffing = {458821: [
        {"person": "Hunsaker, Reed", "position": "Elders Quorum President", "person_uuid": "reed"},
        {"person": "Donoso, Sara", "position": "Relief Society President", "person_uuid": "sara"},
        {"person": "Bonilla, Kevin", "position": "Sunday School President", "person_uuid": "kevin"},
        # youth calling in the SAME roster — must NOT be provisioned
        {"person": "Pulgar, Sebastian", "position": "Teachers Quorum President", "person_uuid": "seb"},
    ]}
    conn = _Conn()
    out = patched.provision_roles(
        conn, _Client(units, org), "stake-1", {"Seabrook Branch (Spanish)": "unit-458821"},
        staffing_by_unit=staffing)

    granted = {r[3]: r[5] for r in conn.rows}   # person_uuid -> calling_name
    assert granted["reed"] == "Elders Quorum President"     # the bug report
    assert granted["sara"] == "Relief Society President"
    assert granted["kevin"] == "Sunday School President"
    assert "seb" not in granted                             # youth quorum stays out
    assert granted["branch-pres"] == "Branch President"     # org-callings lane still works
    assert out["ward_leader"] == 5


def test_org_callings_wins_when_a_person_is_in_both_sources(patched):
    units = [_Unit(127833, "Cary 1st Ward", "WARD")]
    org = {127833: [_pos("luke", "Peterson, Luke", 4, "Bishop")]}
    staffing = {127833: [{"person": "Peterson, Luke", "position": "Priests Quorum President",
                          "person_uuid": "luke"}]}
    conn = _Conn()
    patched.provision_roles(conn, _Client(units, org), "s", {"Cary 1st Ward": "u"},
                            staffing_by_unit=staffing)
    assert [r[5] for r in conn.rows] == ["Bishop"]  # one row, the matrix-gated calling


def test_staffing_alone_provisions_when_org_callings_fails(patched):
    """A unit whose /mlt/api/orgs call throws used to `continue` — losing the whole unit. The
    staffing lane must still provision it."""
    units = [_Unit(44911, "Raleigh 1st Ward", "WARD")]

    class _Broken(_Client):
        def org_callings(self, unit_number):
            raise RuntimeError("LCR 500")

    staffing = {44911: [{"person": "A, B", "position": "Ward Mission Leader", "person_uuid": "wml"}]}
    conn = _Conn()
    patched.provision_roles(conn, _Broken(units, {}), "s", {"Raleigh 1st Ward": "u"},
                            staffing_by_unit=staffing)
    assert [r[3] for r in conn.rows] == ["wml"]


def test_unit_id_falls_back_to_unit_number_when_the_name_does_not_match(patched):
    """A ward renamed between the units upsert and this call still resolves via unit_number."""
    units = [_Unit(44911, "Raleigh 1st Ward (renamed)", "WARD")]
    staffing = {44911: [{"person": "A, B", "position": "Relief Society President",
                         "person_uuid": "rs"}]}
    conn = _Conn()
    patched.provision_roles(conn, _Client(units, {}), "s", {}, staffing_by_unit=staffing,
                            unit_id_by_number={44911: "unit-44911"})
    assert [(r[1], r[3]) for r in conn.rows] == [("unit-44911", "rs")]
