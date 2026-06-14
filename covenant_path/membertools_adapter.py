"""
Adapt the Member Tools `/api/v5/sync` bulk payload → our CovenantPathMember model.

This replaces the FRAGILE one-work source (progress-record + per-person details) with the reliable
Member Tools bulk call (lcr_client.membertools). It fills the covenant-path PROGRESS fields (the data
that used to come from the flaky cluster) + the rich `details` subtree the app's member view shows.

Most of the once-"profile-only" fields turned out to BE in the bulk payload (verified live vs stake
503991, 2026-06-13) and are rescued here so they survive a dead LCR session (the steady-state): the
member DIRECTORY (`households[].members[]`) carries the priesthood OFFICE enum + the per-member
`ordinances[]` (ENDOWMENT), and the unit-wide `templeRecommendStatus[].recommends[]` roster carries
temple-recommend status. Only `patriarchal_blessing` is GENUINELY absent from the whole payload (no
hasPatriarchalBlessing flag, no PATRIARCHAL ordinance type anywhere), so it alone stays the
NEEDS_PROFILE sentinel for covenant_path.report's /mlt profile merge.

person_uuid mapping is load-bearing (wrong choice → duplicated members): VERIFIED live that members
match our DB on `memberUuid` (76/76) and investigators (no memberUuid) on `id` (17/17) — so
`memberUuid or id`.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from backend.milestones import is_at_least_now, member_one_year, turns_at_least
from covenant_path.report import (
    NA,
    NEEDS_PROFILE,
    CovenantPathMember,
    parse_temple_experiences,
    priesthood_from_office,
)


def _person_uuid(p: dict) -> str | None:
    return p.get("memberUuid") or p.get("id")


def _readable_name(names: Any) -> str | None:
    """A display name out of a Member Tools `names` value, tolerant of drift. The LIVE shape is
    {"listed": "Surname, Given"} (verified); older/flat captures use displayName/listPreferred/etc."""
    if isinstance(names, str):
        return names or None
    if isinstance(names, list):
        names = names[0] if names else None
    if isinstance(names, dict):
        for k in ("listed", "spoken", "listPreferred", "listPreferredLocal", "preferredName",
                  "displayName", "fullName"):
            v = names.get(k)
            if isinstance(v, str) and v:
                return v
            if isinstance(v, dict):  # nested name object
                inner = _readable_name(v)
                if inner:
                    return inner
        given = names.get("given") or names.get("givenPreferred") or names.get("givenName")
        family = names.get("family") or names.get("familyPreferred") or names.get("surname")
        if family or given:
            return f"{family}, {given}".strip(", ")
    return None


def _name(p: dict) -> str | None:
    return p.get("displayName") or _readable_name(p.get("names"))


def _friend_uuids(p: dict) -> list[str]:
    """Friends are stored as uuid REFERENCES ({id, memberUuid}), not inline names."""
    return [u for u in (f.get("memberUuid") or f.get("id") for f in (p.get("friends") or [])) if u]


def _sex(p: dict) -> str | None:
    s = (p.get("sex") or "").upper()
    return "F" if s.startswith("F") else "M" if s.startswith("M") else None


def _birth_date(p: dict) -> str | None:
    """A birth date out of a Member Tools person/household record, tolerant of the field's exact
    name/shape (the bulk payload was reverse-engineered, so be defensive). Returns a display string
    (whatever shape the payload carries — the web's parseMemberDate handles ISO, "6 Feb 2026", and
    MM/dd/yy). None when absent, so the /mlt profile merge (covenant_path.report._apply_profile) still
    fills it from the LCR profile record exactly as before — this is purely an ADDITIVE rescue so the
    birth date (and thus every age-gated milestone/eligibility) survives when the LCR session is dead
    but the 45-day Member Tools token is alive (the steady-state daily-sync path)."""
    # Flat candidates first (the common Member Tools shape).
    for k in ("birthDate", "birthdate", "dateOfBirth", "birthDateString"):
        v = p.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    # Nested LCR-style `birth` object ({date|dateDisplay|displayDate: ...}) — the convention the LCR
    # member-list + member-profile records use (see member_profile.extract_fields / _build_member_maps).
    birth = p.get("birth")
    if isinstance(birth, dict):
        for k in ("dateDisplay", "displayDate", "date", "display"):
            v = birth.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        d = birth.get("date")
        if isinstance(d, dict):
            for k in ("display", "dateDisplay", "value"):
                v = d.get(k)
                if isinstance(v, str) and v.strip():
                    return v.strip()
    return None


# --- ministering / calling / demographics from the bulk payload --------------------------------
# The covenant-path PERSON record carries NO ministering / calling / priesthood / recommend (verified
# against the Member Tools sync schema — see SyncPerson in rickybloomfield/Mission-KPIs). But the WHOLE
# payload DOES carry the unit-wide ministering org (`ministeringBrothers`/`ministeringSisters`) and the
# member directory (`households[].members[].positions`) — the authoritative source the official-app
# clone uses for these exact Golden-Hour flags. So we rescue them HERE (top-level payload) rather than
# from the per-person record, instead of leaving them as the NEEDS_PROFILE sentinel for a /mlt merge
# that never runs once the LCR session dies. (#data-gap ministering; the same "better not worse" win
# as the birth_date rescue.) Algorithm ported 1:1 from SyncGoldenHourIndex.swift.


def _household_members(payload: dict) -> list[tuple[str, dict, int | None]]:
    """[(member_uuid, member_record, household_unit_number)] across every household — the member
    directory. The Member Tools household member is keyed by `uuid`, which equals a covenant person's
    `memberUuid` (verified). Tolerant of the older flat shape (memberUuid/id)."""
    out: list[tuple[str, dict, int | None]] = []
    for hh in (payload.get("households") or []):
        unum = hh.get("unitNumber")
        for m in (hh.get("members") or []):
            if isinstance(m, dict):
                u = m.get("uuid") or m.get("memberUuid") or m.get("id")
                if u:
                    out.append((u, m, unum))
    return out


def _calling_index(payload: dict) -> dict[str, list[str]]:
    """uuid -> [calling name, ...] from the directory's `positions`. A non-empty list = has a calling
    (the same signal LCR's per-member profile gives), and the names surface in the detail view. Empty
    list for a directory member with no positions (a real 'No calling'); absent for someone not in the
    directory (unknown -> stays NEEDS_PROFILE so the merge/last-good preserves)."""
    idx: dict[str, list[str]] = {}
    for uuid, m, _unum in _household_members(payload):
        if "positions" not in m:
            continue
        names = [p.get("name") for p in (m.get("positions") or [])
                 if isinstance(p, dict) and p.get("name")]
        # setdefault-union across multi-household listings (a member can appear in two households).
        cur = idx.setdefault(uuid, [])
        for n in names:
            if n not in cur:
                cur.append(n)
    return idx


# Leadership callings tracked for the staffing view (#12): the ward-mission team, the org presidencies,
# and the bishopric. Keeps the per-unit roster small (the directory carries ~270 distinct callings).
_TRACKED_CALLING = re.compile(
    r"mission leader|missionary|president|counselor|bishop|presidency", re.I)


def staffing_by_unit(payload: dict) -> dict[int, list[dict]]:
    """unitNumber -> [{position, person, person_uuid, set_apart}] for the LEADERSHIP-relevant callings,
    from the bulk household directory (#12). Grouped by the POSITION's own unitNumber (a person can hold
    a calling in a different unit than their household), so each unit's roster is correct. Stored on the
    `units` row (units.staffing) where the existing units_select RLS scopes it per unit."""
    out: dict[int, list[dict]] = {}
    for uuid, m, _unum in _household_members(payload):
        person = _name(m)
        for pos in (m.get("positions") or []):
            if not isinstance(pos, dict):
                continue
            pname = pos.get("name")
            punit = pos.get("unitNumber")
            if not (pname and punit) or not _TRACKED_CALLING.search(pname):
                continue
            out.setdefault(int(punit), []).append({
                "position": pname,
                "person": person,
                "person_uuid": uuid,
                "set_apart": bool(pos.get("setApart")),
            })
    return out


def missionaries_by_unit(payload: dict) -> dict[int, list[dict]]:
    """Per-unit full-time missionary COMPANIONSHIPS from the bulk `missionariesAssigned` — session-
    independent (no /mlt server action). Each `missionariesAssigned` entry IS a companionship:
    `{unitNumbers, phone, email, mission, missionaries:[{uuid, names, sex, email, type}]}`. We expand
    each across every unit it serves and keep the companionship grouping (members + shared phone/email).
    Mission-wide companionships (no `unitNumbers`) have no ward → skipped for the per-unit view."""
    out: dict[int, list[dict]] = {}
    for c in (payload.get("missionariesAssigned") or []):
        if not isinstance(c, dict):
            continue
        units = c.get("unitNumbers") or []
        if not units:
            continue
        mission = c.get("mission") or {}
        comp = {
            "phone": c.get("phone") or mission.get("phone"),
            "email": c.get("email") or mission.get("email"),
            "mission_name": mission.get("name"),
            "missionaries": [
                {"uuid": m.get("uuid"), "name": _name(m), "email": m.get("email"), "type": m.get("type")}
                for m in (c.get("missionaries") or []) if isinstance(m, dict)
            ],
        }
        for u in units:
            try:
                out.setdefault(int(u), []).append(comp)
            except (TypeError, ValueError):
                continue
    return out


def _sex_from_household(m: dict) -> str | None:
    s = (m.get("sex") or "").upper()
    return "F" if s.startswith("F") else "M" if s.startswith("M") else None


def _sex_index(payload: dict) -> dict[str, str]:
    """uuid -> 'M'/'F' from the directory (authoritative for sex; the covenant person's `sex` is also
    present but the directory covers everyone incl. friends)."""
    idx: dict[str, str] = {}
    for uuid, m, _unum in _household_members(payload):
        s = _sex_from_household(m)
        if s:
            idx.setdefault(uuid, s)
    return idx


# --- priesthood office / endowment / temple recommend from the bulk payload ----------------------
# (#data-gap, 2026-06-13.) Verified LIVE against stake 503991's /api/v5/sync that these three of the
# four still-"profile-only" fields ARE in the bulk payload after all (they were left for the /mlt merge
# only because the FIRST pass read the covenant PERSON record, which omits them — exactly how birthday
# was missed). They live in the member DIRECTORY + the unit-wide temple-recommend roster, both of which
# renew with the 45-day Member Tools token, so we rescue them HERE instead of leaking the NEEDS_PROFILE
# sentinel once the LCR session dies (the steady-state). Patriarchal blessing is the ONLY one genuinely
# absent from the whole payload — it stays the sentinel for the /mlt merge.
#
#   • priesthood office: `households[].members[].priesthood` is a direct enum
#     (DEACON/TEACHER/PRIEST/ELDER/HIGH_PRIEST/BISHOP/SEVENTY/PATRIARCH/APOSTLE, or absent), the same
#     vocabulary report.priesthood_from_office already maps. Absent = no current office (a real "No").
#   • endowment (living_ordinance): `households[].members[].ordinances[]` carries `type == "ENDOWMENT"`
#     when endowed. A directory member with an ordinances list but no ENDOWMENT = a real "No".
#   • temple recommend: `templeRecommendStatus[].recommends[]` is a unit-wide roster keyed by
#     `memberUuid` with {status: ACTIVE/EXPIRED/ISSUED/CANCELED, type: REGULAR/LIMITED_USE, expiration}.
#     Mapped to the same Active/Expired/No labels member_profile._recommend_label emits.


def _priesthood_office_index(payload: dict) -> dict[str, str]:
    """uuid -> current priesthood OFFICE (upper-case enum) from the directory. EVERY directory member is
    indexed: the live payload OMITS the `priesthood` key entirely for members with no office (women,
    un-ordained males), so directory membership — not key presence — is the "we know this member"
    signal. A missing/empty office maps to "" (a real "no office", which priesthood_from_office turns
    into N/A via the eligibility gate). A member ABSENT from the directory is simply not in the index
    (-> the adapter keeps the sentinel for the /mlt merge / last-good)."""
    idx: dict[str, str] = {}
    for uuid, m, _unum in _household_members(payload):
        office = m.get("priesthood")
        office = office if isinstance(office, str) else ""
        # An office anywhere wins over "" across multi-household listings.
        if uuid not in idx or (office and not idx[uuid]):
            idx[uuid] = office
    return idx


def _endowed_index(payload: dict) -> dict[str, bool]:
    """uuid -> endowed? from the directory's `ordinances` list (type == ENDOWMENT). Only members whose
    directory record carries an `ordinances` list are indexed (a present list is authoritative: no
    ENDOWMENT entry = not endowed). Absent from the index -> the adapter keeps the sentinel."""
    idx: dict[str, bool] = {}
    for uuid, m, _unum in _household_members(payload):
        ords = m.get("ordinances")
        if not isinstance(ords, list):
            continue
        endowed = any(isinstance(o, dict) and o.get("type") == "ENDOWMENT" for o in ords)
        # OR across multi-household listings: a True anywhere wins.
        idx[uuid] = idx.get(uuid, False) or endowed
    return idx


# The covenant-path `baptism_date` convention IS the CONFIRMATION date (verified live: for all 74/74
# covenant members that carry both, the person record's `confirmationDate` equals the directory's
# CONFIRMATION ordinance date, to the day). BAPTISM is the same-day fallback when CONFIRMATION is
# absent. ISO `YYYY-MM-DD` strings in the live payload.
_BAPTISM_DATE_ORDINANCE_PREFERENCE = ("CONFIRMATION", "BAPTISM")


def _baptism_date_index(payload: dict) -> dict[str, str]:
    """uuid -> baptism (confirmation) date from the directory's `ordinances[]`. This is the AUTHORITATIVE
    bulk-payload fallback for `baptism_date` when a covenant person's own record omits `confirmationDate`
    — the case that left BIC children (e.g. the Lambert children, unit 367575) leaking the NEEDS_PROFILE
    sentinel as their baptism_date forever, because their `covenantPathMembers` entry is a stub (only
    id/names/unit) while their DIRECTORY record carries BAPTISM+CONFIRMATION dates. Prefers CONFIRMATION
    (== the confirmationDate convention) then BAPTISM (same day). Absent -> not indexed (sentinel stays,
    /mlt merge / last-good preserves)."""
    idx: dict[str, str] = {}
    for uuid, m, _unum in _household_members(payload):
        ords = m.get("ordinances")
        if not isinstance(ords, list):
            continue
        by_type = {o.get("type"): o.get("date") for o in ords
                   if isinstance(o, dict) and o.get("type") and o.get("date")}
        for t in _BAPTISM_DATE_ORDINANCE_PREFERENCE:
            d = by_type.get(t)
            if isinstance(d, str) and d.strip():
                idx.setdefault(uuid, d.strip()[:10])  # YYYY-MM-DD; first (CONFIRMATION) wins
                break
    return idx


# A temple-recommend roster status that means "has a usable/known recommend record" for the label.
_RECOMMEND_STATUS_LABEL = {"ACTIVE": "Active", "EXPIRED": "Expired"}


def _recommend_index(payload: dict) -> dict[str, str]:
    """uuid -> temple-recommend label ('Active'/'Expired'/'No') from the unit-wide
    `templeRecommendStatus[].recommends[]` roster. Keyed by `memberUuid`. A member with an ACTIVE
    recommend anywhere is 'Active'; else EXPIRED is 'Expired'; any other status (ISSUED/CANCELED) is
    'No'. Members NOT in any roster entry are absent from the index — when the roster IS present in the
    payload, a DIRECTORY member missing from it genuinely has no recommend ('No', resolved in
    adapt_person via directory_uuids + recommend_present); when the whole roster container is absent
    (degraded sync) recommend stays unknown for everyone. Mirrors member_profile._recommend_label so
    the values match the /mlt-sourced ones."""
    idx: dict[str, str] = {}
    for unit in (payload.get("templeRecommendStatus") or []):
        for r in (unit.get("recommends") or []):
            if not isinstance(r, dict):
                continue
            uuid = r.get("memberUuid")
            if not uuid:
                continue
            label = _RECOMMEND_STATUS_LABEL.get(r.get("status"), "No")
            cur = idx.get(uuid)
            # Prefer the strongest label across multiple records (Active > Expired > No).
            if label == "Active" or (label == "Expired" and cur != "Active") or cur is None:
                idx[uuid] = label
    return idx


def _directory_uuids(payload: dict) -> set[str]:
    """Every uuid present in the member directory — used to distinguish a real 'No recommend' (a
    directory member absent from the recommend roster) from 'unknown' (someone not in the directory)."""
    return {uuid for uuid, _m, _u in _household_members(payload)}


class MinisteringIndex:
    """O(1) ministering lookups for the WHOLE stake, built once from the bulk payload's unit-wide
    EQ/RS org. Ported from SyncGoldenHourIndex.swift (the official-app clone's authoritative source):

      • EQ (`ministeringBrothers`) assigns per HOUSEHOLD — a member "has ministering brothers" when ANY
        of their households is assigned to a brothers companionship.
      • RS (`ministeringSisters`) assigns per INDIVIDUAL sister — a member "has ministering sisters"
        when their own uuid is in a companionship's `sisters`.
      • "has a ministering ASSIGNMENT" (ministers to others) = their uuid is a `companions` member on
        either side.

    Unit-coverage semantics matter: being in an assigned set is positive proof (-> Yes) regardless of
    coverage; NOT being assigned is a real 'No' ONLY when that member's unit's org is in this payload,
    else it's genuinely unknown (-> None, which the adapter leaves as the NEEDS_PROFILE sentinel so the
    merge/last-good preserves rather than writing a false 'No')."""

    def __init__(self, payload: dict):
        # member_uuid -> set(household_uuid); member_uuid -> set(unit_number)
        self.households_by_member: dict[str, set[str]] = {}
        self.units_by_member: dict[str, set[int]] = {}
        self.household_name: dict[str, str] = {}
        for hh in (payload.get("households") or []):
            hh_uuid = hh.get("uuid")
            if hh_uuid and hh.get("name"):
                self.household_name[hh_uuid] = hh["name"]
            unum = hh.get("unitNumber")
            for m in (hh.get("members") or []):
                if not isinstance(m, dict):
                    continue
                u = m.get("uuid") or m.get("memberUuid") or m.get("id")
                if not u:
                    continue
                if hh_uuid:
                    self.households_by_member.setdefault(u, set()).add(hh_uuid)
                if unum is not None:
                    self.units_by_member.setdefault(u, set()).add(int(unum))

        self.minister_uuids: set[str] = set()           # ministers to others (EQ or RS companions)
        self.sisters_assigned: set[str] = set()         # RS: ministered-to sisters (by member uuid)
        self.households_with_brothers: set[str] = set()  # EQ: ministered-to households (by hh uuid)
        self.brothers_units: set[int] = set()
        self.sisters_units: set[int] = set()
        # detail maps (names behind the booleans)
        self.brothers_by_household: dict[str, set[str]] = {}   # hh uuid -> brother (minister) uuids
        self.sisters_by_member: dict[str, set[str]] = {}       # member uuid -> sister (minister) uuids

        for org in (payload.get("ministeringBrothers") or []):
            unum = org.get("unitNumber")
            if unum is not None:
                self.brothers_units.add(int(unum))
            for district in (org.get("districts") or []):
                for comp in (district.get("companionships") or []):
                    comps = [c for c in (comp.get("companions") or []) if c]
                    households = [h for h in (comp.get("households") or []) if h]
                    self.minister_uuids.update(comps)
                    for hh in households:
                        self.households_with_brothers.add(hh)
                        self.brothers_by_household.setdefault(hh, set()).update(comps)

        for org in (payload.get("ministeringSisters") or []):
            unum = org.get("unitNumber")
            if unum is not None:
                self.sisters_units.add(int(unum))
            for district in (org.get("districts") or []):
                for comp in (district.get("companionships") or []):
                    comps = [c for c in (comp.get("companions") or []) if c]
                    sisters = [s for s in (comp.get("sisters") or []) if s]
                    self.minister_uuids.update(comps)
                    for sis in sisters:
                        self.sisters_assigned.add(sis)
                        self.sisters_by_member.setdefault(sis, set()).update(comps)

    @property
    def present(self) -> bool:
        """Whether the payload carried ANY ministering org at all (else every lookup is unknown)."""
        return bool(self.brothers_units or self.sisters_units
                    or self.minister_uuids or self.sisters_assigned)

    @staticmethod
    def _state(assigned: bool, unit_covered: bool) -> bool | None:
        if assigned:
            return True
        return False if unit_covered else None

    def has_ministers(self, uuid: str) -> bool | None:
        """'has ministering brothers OR sisters assigned to them' (the `ministering_brothers_sisters`
        field). None = unknown (member's unit org not in this payload)."""
        households = self.households_by_member.get(uuid, set())
        units = self.units_by_member.get(uuid, set())
        has_brothers = bool(households & self.households_with_brothers)
        has_sisters = uuid in self.sisters_assigned
        b = self._state(has_brothers, bool(units & self.brothers_units))
        s = self._state(has_sisters, bool(units & self.sisters_units))
        # combine the two sides: a Yes on either is Yes; else No if either side is known; else unknown.
        if b is True or s is True:
            return True
        if b is False or s is False:
            return False
        return None

    def has_assignment(self, uuid: str) -> bool | None:
        """'ministers to others' (the `ministering_assignment` field). None = unknown."""
        units = self.units_by_member.get(uuid, set())
        covered = bool(units & (self.brothers_units | self.sisters_units))
        return self._state(uuid in self.minister_uuids, covered)

    def minister_names(self, uuid: str, name_by_uuid: dict[str, str]) -> list[str]:
        """Names of the brothers + sisters who minister TO this person (for the detail view)."""
        out: list[str] = []
        for hh in self.households_by_member.get(uuid, set()):
            for b in self.brothers_by_household.get(hh, set()):
                if b != uuid and name_by_uuid.get(b) and name_by_uuid[b] not in out:
                    out.append(name_by_uuid[b])
        for s in self.sisters_by_member.get(uuid, set()):
            if s != uuid and name_by_uuid.get(s) and name_by_uuid[s] not in out:
                out.append(name_by_uuid[s])
        return out


def _yn_or_sentinel(state: bool | None) -> str:
    """Yes/No when known; the NEEDS_PROFILE sentinel when unknown — so an unknown leaves last-good
    intact via the merge-upsert rather than writing a false 'No'."""
    return "Yes" if state is True else "No" if state is False else NEEDS_PROFILE


def _parse_date(s: Any) -> date | None:
    if not isinstance(s, str) or not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(s[:len(fmt) + 6 if "%f" in fmt else len(s)], fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except (ValueError, TypeError):
        return None


def _weeks_since_attendance(sacrament: list | None) -> int | None:
    """Weeks since the most recent ATTENDED sacrament meeting (Member Tools gives the raw list, not a
    precomputed count). None when there's no attended record."""
    dates = [d for d in (_parse_date(s.get("date")) for s in (sacrament or []) if s.get("attended")) if d]
    if not dates:
        return None
    return max(0, (date.today() - max(dates)).days // 7)


def _details_subtree(p: dict, name_by_uuid: dict[str, str],
                     ministering: "MinisteringIndex | None" = None,
                     calling_names: list[str] | None = None) -> dict:
    """The rich progress-only subtree for the member view, in our canonical `details` shape — sourced
    from Member Tools instead of the one-work details endpoint. The PROGRESS sub-keys come from the
    person record; the ministering minister-NAMES + calling NAMES now ALSO come from the bulk payload's
    unit-wide org + member directory (rescued here so they survive a dead LCR session — they used to be
    left for the /mlt merge). templeOrdinances stays profile-only (not in the bulk payload).
    Friend names are resolved from `name_by_uuid` (friends are stored as uuid refs)."""
    sacrament = [
        {"label": s.get("date"), "attended": bool(s.get("attended")), "date": s.get("date")}
        for s in (p.get("sacramentAttendance") or [])
    ]
    friends = [{"name": name_by_uuid.get(u), "uuid": u, "unit": None, "inStake": None}
               for u in _friend_uuids(p)]
    lessons = [
        {
            "name": tr.get("title"),
            "taught": None,
            "principles": [
                {"name": pr.get("title"), "memberPresent": bool(pr.get("memberPresent")),
                 "taughtLevel": pr.get("taught")}
                for pr in (tr.get("principles") or [])
            ],
        }
        for tr in (p.get("teachingRecords") or [])
    ]
    commitments = [c.get("title") for c in (p.get("commitments") or []) + (p.get("otherCommitments") or [])
                   if c.get("title")]
    uuid = _person_uuid(p)
    # Minister NAMES (who ministers TO this person) split brothers/sisters from the unit-wide org —
    # the detail view shows them, and they used to be left blank until the (now-dead-in-steady-state)
    # /mlt merge. We don't have a per-name EQ/RS split cheaply, so put resolved names under
    # ministeringBrothers (the detail view concatenates brothers + sisters anyway).
    minister_names = ministering.minister_names(uuid, name_by_uuid) if (ministering and uuid) else []
    out: dict[str, Any] = {
        "baptismGoalDate": p.get("baptismGoalDate"),
        "firstLesson": p.get("firstTaught"),
        "nextScheduledEvent": p.get("nextAppointment"),
        "weeksSinceLastAttendance": _weeks_since_attendance(p.get("sacramentAttendance")),
        "sacrament": sacrament,
        "friends": friends,
        "lessons": lessons,
        "commitments": commitments,
        "sealedToParents": p.get("sealedToParents"),
        "sealedToSpouse": p.get("sealedToSpouse"),
        "source": "membertools",  # provenance, so the app/diagnostics can tell where it came from
    }
    if minister_names:
        out["ministeringBrothers"] = minister_names
    if calling_names:
        out["callings"] = calling_names
    return out


def unit_names(payload: dict) -> dict[int, str]:
    """{unitNumber: name} from the `units` tree (root + childUnits), for mapping members to a ward."""
    out: dict[int, str] = {}

    def walk(u: dict):
        if isinstance(u, dict):
            if u.get("unitNumber") is not None and u.get("name"):
                out[int(u["unitNumber"])] = u["name"]
            for c in (u.get("childUnits") or []):
                walk(c)

    for u in (payload.get("units") or []):
        walk(u)
    return out


def context_from_sync(payload: dict):
    """Build a UserContext (stake identity + child units) from the Member Tools /api/v5/sync `units`
    tree — so the daily sync has the stake/ward structure it needs WITHOUT a live LCR session (which
    dies within days). `positions`/`roles` are empty (those are an LCR concept, re-checked on enroll),
    so role provisioning + the eligibility re-check stay best-effort. Returns None if `units` is empty."""
    from lcr_client.models import UnitRef, UserContext
    units = payload.get("units") or []
    if not units:
        return None
    root = units[0]
    children = [UnitRef(c.get("name"), c.get("unitNumber"), c.get("unitType"))
                for c in (root.get("childUnits") or [])]
    return UserContext(
        individual_id=None, active_position=None,
        unit_name=root.get("name"), unit_number=root.get("unitNumber"),
        positions=[], roles=[], child_units=children, raw=root)


def _priesthood_endowment_recommend(
        uuid: str | None, *, sex: str | None, birth_date: str | None, baptism_date: str | None,
        office_by_uuid: dict[str, str] | None, endowed_by_uuid: dict[str, bool] | None,
        recommend_by_uuid: dict[str, str] | None, directory_uuids: set[str] | None,
        recommend_present: bool = False,
) -> tuple[str, str, str, str]:
    """Compute (aaronic, melchizedek, living_ordinance, temple_recommend) from the bulk-payload
    indexes, applying the SAME eligibility gating report._apply_profile applies — so the values match
    the /mlt-sourced ones whether the merge runs (live LCR) or not (steady-state dead session). Each
    field stays NEEDS_PROFILE when the payload can't determine it, so the merge/last-good preserves it
    (purely additive). Mirrors report._apply_profile's priesthood/endowment/recommend blocks 1:1."""
    aaronic = melch = living = recommend = NEEDS_PROFILE
    if not uuid:
        return aaronic, melch, living, recommend
    em = {"sex": sex, "birth_date": birth_date, "baptism_date": baptism_date}
    male = sex == "M"

    # Priesthood from the directory's current office (authoritative). Same eligibility gates as
    # _apply_profile: Aaronic = male & turning-12; Melchizedek = male & 18+ now & member 1yr; else N/A.
    if office_by_uuid is not None and uuid in office_by_uuid:
        a, mel = priesthood_from_office(office_by_uuid[uuid] or None)
        aaronic = a if (male and turns_at_least(em, 12)) else NA
        melch = mel if (male and is_at_least_now(em, 18) and member_one_year(em)) else NA

    # Endowment (living_ordinance). A directory member with an ordinances list = authoritative; ENDOWMENT
    # present = "Yes", else "No". Gate an ineligible "No" (under 18 / member <1yr) to N/A — matching
    # _apply_profile (a "No" misleads when they can't yet be endowed). A genuine "Yes" is always kept.
    if endowed_by_uuid is not None and uuid in endowed_by_uuid:
        if endowed_by_uuid[uuid]:
            living = "Yes"
        elif is_at_least_now(em, 18) and member_one_year(em):
            living = "No"
        else:
            living = NA

    # Temple recommend. The roster is unit-wide: an explicit roster label wins; a DIRECTORY member with
    # no roster entry genuinely has no recommend ("No") — BUT only when the roster is actually PRESENT in
    # this payload. If the whole `templeRecommendStatus` container is absent (a degraded/minimal sync),
    # recommend is genuinely UNKNOWN for everyone → stay the sentinel so last-good is preserved, never a
    # false stake-wide "No". Someone not in the directory at all also stays the sentinel.
    if recommend_by_uuid is not None and uuid in recommend_by_uuid:
        recommend = recommend_by_uuid[uuid]
    elif recommend_present and directory_uuids is not None and uuid in directory_uuids:
        recommend = "No"
    return aaronic, melch, living, recommend


def adapt_person(p: dict, kind: str, unit_name_by_number: dict[int, str],
                 name_by_uuid: dict[str, str], birth_by_uuid: dict[str, str] | None = None,
                 ministering: "MinisteringIndex | None" = None,
                 calling_by_uuid: dict[str, list[str]] | None = None,
                 sex_by_uuid: dict[str, str] | None = None,
                 office_by_uuid: dict[str, str] | None = None,
                 endowed_by_uuid: dict[str, bool] | None = None,
                 recommend_by_uuid: dict[str, str] | None = None,
                 directory_uuids: set[str] | None = None,
                 recommend_present: bool = False,
                 baptism_by_uuid: dict[str, str] | None = None) -> CovenantPathMember:
    """One Member Tools covenant-path person → CovenantPathMember. Covenant-path PROGRESS fields are
    filled from the bulk payload; only patriarchal_blessing stays the NEEDS_PROFILE sentinel (it is
    GENUINELY absent from the whole /api/v5/sync payload — verified live) so the /mlt merge fills it
    from the reliable cluster.

    RESCUED from the bulk payload (else they'd persist as the leaking sentinel once the LCR session
    dies — the "better not worse" win):
      • baptism_date — person `confirmationDate`, else the directory's CONFIRMATION/BAPTISM ordinance
        (so a stub covenant record — the Lambert BIC children — still gets its date, never the sentinel).
      • birth_date  — person record, else household roster.
      • ministering_brothers_sisters / ministering_assignment — the unit-wide EQ/RS org (`ministering`).
      • calling — the member directory's `positions` (with the calling names in `details`).
      • sex — the directory (more complete than the covenant person's own `sex`).
      • aaronic/melchizedek priesthood — the directory's `priesthood` OFFICE enum (#data-gap 2026-06-13).
      • living_ordinance (endowment) — the directory's `ordinances[]` (type ENDOWMENT).
      • temple_recommend — the unit-wide `templeRecommendStatus[].recommends[]` roster.
    Each stays the sentinel (or None) when the payload lacks it → the /mlt merge fills it as before, so
    this is purely additive (never a regression). The priesthood/endowment/recommend values apply the
    SAME eligibility gating as report._apply_profile so they match the /mlt-sourced ones."""
    unum = p.get("unitNumber")
    friend_uuids = _friend_uuids(p)
    friend_names = [name_by_uuid[u] for u in friend_uuids if name_by_uuid.get(u)]
    uuid = _person_uuid(p)
    birth = _birth_date(p) or ((birth_by_uuid or {}).get(uuid) if uuid else None)
    sex = _sex(p) or ((sex_by_uuid or {}).get(uuid) if uuid else None)
    # Calling: directory positions are the authoritative bulk-payload signal. A present-but-empty list
    # is a real 'No'; absent (member not in directory) leaves the sentinel for the merge/last-good.
    calling_names = (calling_by_uuid or {}).get(uuid) if uuid else None
    if uuid and calling_by_uuid is not None and uuid in calling_by_uuid:
        calling = "Yes" if calling_names else "No"
    else:
        calling = NEEDS_PROFILE
    # Ministering: the unit-wide org is the authoritative bulk-payload signal (Yes/No/unknown).
    has_min = ministering.has_ministers(uuid) if (ministering and uuid) else None
    gives_min = ministering.has_assignment(uuid) if (ministering and uuid) else None
    # baptism_date = the CONFIRMATION date (the covenant-path convention). Prefer the covenant person's
    # own `confirmationDate`; fall back to the DIRECTORY's CONFIRMATION/BAPTISM ordinance (verified
    # identical to the day for 74/74 members that carry both). A stub covenant record (only id/names/
    # unit — the Lambert BIC children) has no confirmationDate but DOES carry the ordinance in the
    # directory, so this rescue stops baptism_date leaking the NEEDS_PROFILE sentinel forever.
    baptism_date = p.get("confirmationDate") or (
        (baptism_by_uuid or {}).get(uuid) if uuid else None)
    baptism_for_gate = baptism_date
    aaronic, melch, living, recommend = _priesthood_endowment_recommend(
        uuid, sex=sex, birth_date=birth, baptism_date=baptism_for_gate,
        office_by_uuid=office_by_uuid, endowed_by_uuid=endowed_by_uuid,
        recommend_by_uuid=recommend_by_uuid, directory_uuids=directory_uuids,
        recommend_present=recommend_present)
    # Temple experiences (family_name_prepared / first_temple_visit) ARE in the bulk payload — under
    # the person's `otherCommitments` ({title, interested}), NOT the one-work `newMemberOtherCommitments`
    # ({name, isKeeping}). adapt_person used to leave both as the NEEDS_PROFILE sentinel, so once the LCR
    # session died (the steady state) they NEVER filled — and the Green Level Ward restore blanked them
    # for every re-added member. Extract them here with the shared parser, applying the SAME age gate as
    # report._apply_profile (an ineligible "No" — not yet turning 12 — shows as N/A). Absent list ->
    # sentinel, so the /mlt merge / last-good still wins when the bulk genuinely lacks it.
    other_commitments = p.get("otherCommitments")
    if other_commitments:
        family_name_prepared, first_temple_visit = parse_temple_experiences(other_commitments)
        em_t = {"sex": sex, "birth_date": birth, "baptism_date": baptism_for_gate}
        if not turns_at_least(em_t, 12):
            if first_temple_visit == "No":
                first_temple_visit = NA
            if family_name_prepared == "No":
                family_name_prepared = NA
    else:
        family_name_prepared = first_temple_visit = NEEDS_PROFILE
    return CovenantPathMember(
        name=_name(p),
        unit=unit_name_by_number.get(int(unum)) if unum is not None else None,
        unit_number=int(unum) if unum is not None else None,
        person_uuid=_person_uuid(p),
        kind=kind,
        sex=sex,
        # covenant-path PROGRESS (from Member Tools — the data we're rescuing from the fragile cluster).
        # baptism_date prefers the person's confirmationDate, then the directory ordinance (above); only
        # genuinely-absent (neither source) leaves the sentinel for the /mlt merge / last-good.
        baptism_date=baptism_date or NEEDS_PROFILE,
        baptism_goal_date=p.get("baptismGoalDate"),
        friends="Yes" if friend_uuids else "No",   # friends are uuid refs — count the array, not names
        friends_count=len(friend_uuids),
        friends_summary=", ".join(friend_names) or None,
        weeks_since_last_attendance=_weeks_since_attendance(p.get("sacramentAttendance")),
        details=_details_subtree(p, name_by_uuid, ministering=ministering, calling_names=calling_names),
        # birth_date / ministering / calling / sex: rescued from the bulk payload when present (else
        # sentinel/None → /mlt merge, as before — purely additive).
        birth_date=birth,
        calling=calling,
        ministering_brothers_sisters=_yn_or_sentinel(has_min),
        ministering_assignment=_yn_or_sentinel(gives_min),
        # Rescued from the directory + recommend roster (else they'd leak the sentinel once the LCR
        # session dies). Each is NEEDS_PROFILE when the payload couldn't determine it → /mlt merge.
        aaronic_priesthood=aaronic,
        melchizedek_priesthood=melch,
        temple_recommend=recommend,
        living_ordinance=living,
        # Temple experiences — rescued from the bulk `otherCommitments` (see above) instead of leaking
        # the sentinel; the /mlt merge still fills them when the bulk lacks the list.
        family_name_prepared=family_name_prepared,
        first_temple_visit=first_temple_visit,
        # Still PROFILE-only: patriarchal_blessing is GENUINELY absent from the whole bulk payload
        # (no hasPatriarchalBlessing flag, no PATRIARCHAL ordinance) — left for the /mlt merge.
        patriarchal_blessing=NEEDS_PROFILE,
        membership_duration=None,
    )


# Which top-level array maps to which `kind` (the app's being-taught vs new-members split).
_ARRAYS = {
    "covenantPathInvestigators": "investigator",
    "covenantPathMembers": "new_member",
    "covenantPathReturningMembers": "returning",
}


def adapt_sync(payload: dict, include_returning: bool = True) -> list[CovenantPathMember]:
    """The whole /api/v5/sync payload → CovenantPathMember rows. Covenant-path progress + ministering +
    calling + birth/sex + priesthood/endowment/temple-recommend are filled from the bulk payload; only
    patriarchal_blessing (genuinely absent from the payload) awaits the /mlt merge. De-dupes by
    person_uuid (members can appear under multiple arrays); a real person_uuid is required (else the DB
    upsert key is meaningless)."""
    units = unit_names(payload)
    name_by_uuid = _name_index(payload)
    birth_by_uuid = _birth_index(payload)
    ministering = MinisteringIndex(payload)
    calling_by_uuid = _calling_index(payload)
    sex_by_uuid = _sex_index(payload)
    office_by_uuid = _priesthood_office_index(payload)
    endowed_by_uuid = _endowed_index(payload)
    recommend_by_uuid = _recommend_index(payload)
    baptism_by_uuid = _baptism_date_index(payload)
    directory_uuids = _directory_uuids(payload)
    # Whether the unit-wide temple-recommend roster is present AT ALL — gates the "directory member with
    # no roster entry = a real 'No'" fallback. If the whole container is missing (degraded sync), every
    # member's recommend is genuinely unknown -> sentinel (preserve last-good), not a false stake 'No'.
    recommend_present = bool(payload.get("templeRecommendStatus"))
    out: list[CovenantPathMember] = []
    seen: set[str] = set()
    for arr, kind in _ARRAYS.items():
        if arr == "covenantPathReturningMembers" and not include_returning:
            continue
        for p in (payload.get(arr) or []):
            uuid = _person_uuid(p)
            if not uuid or uuid in seen:
                continue
            seen.add(uuid)
            out.append(adapt_person(p, kind, units, name_by_uuid, birth_by_uuid,
                                    ministering=ministering, calling_by_uuid=calling_by_uuid,
                                    sex_by_uuid=sex_by_uuid, office_by_uuid=office_by_uuid,
                                    endowed_by_uuid=endowed_by_uuid,
                                    recommend_by_uuid=recommend_by_uuid,
                                    directory_uuids=directory_uuids,
                                    recommend_present=recommend_present,
                                    baptism_by_uuid=baptism_by_uuid))
    return out


def _birth_index(payload: dict) -> dict[str, str]:
    """uuid → birth-date display, from the covenant persons + every household member — so a covenant
    person whose own record omits the birth date can still resolve it from their household roster
    record (the same fallback the name index uses). Best-effort; empty when the payload has no birth
    info (then birth_date stays None and the /mlt merge fills it, exactly as before)."""
    idx: dict[str, str] = {}
    for arr in _ARRAYS:
        for p in (payload.get(arr) or []):
            u, b = _person_uuid(p), _birth_date(p)
            if u and b:
                idx[u] = b
    for hh in (payload.get("households") or []):
        for m in (hh.get("members") or []):
            if isinstance(m, dict):
                u = m.get("uuid") or m.get("memberUuid") or m.get("id")
                b = _birth_date(m)
                if u and b:
                    idx.setdefault(u, b)
    return idx


def _name_index(payload: dict) -> dict[str, str]:
    """uuid → display name, from the covenant persons + every household member — so friend uuid refs
    (and any other cross-reference) resolve to a readable name."""
    idx: dict[str, str] = {}
    for arr in _ARRAYS:
        for p in (payload.get(arr) or []):
            u, nm = _person_uuid(p), _name(p)
            if u and nm:
                idx[u] = nm
    for hh in (payload.get("households") or []):
        for m in (hh.get("members") or []):
            if isinstance(m, dict):
                u = m.get("uuid") or m.get("memberUuid") or m.get("id")
                nm = _name(m)
                if u and nm:
                    idx[u] = nm
    return idx
