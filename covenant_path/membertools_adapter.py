"""
Adapt the Member Tools `/api/v5/sync` bulk payload → our CovenantPathMember model.

This replaces the FRAGILE one-work source (progress-record + per-person details) with the reliable
Member Tools bulk call (lcr_client.membertools). It fills the covenant-path PROGRESS fields (the data
that used to come from the flaky cluster) + the rich `details` subtree the app's member view shows.
The PROFILE-sourced fields (patriarchal_blessing, temple_recommend, ministering, calling, priesthood,
birth_date, …) are left as the NEEDS_PROFILE sentinel — covenant_path.report's existing /mlt profile
merge fills those from the reliable /mlt cluster, exactly as before. So this is a SURGICAL swap of
only the broken part.

person_uuid mapping is load-bearing (wrong choice → duplicated members): VERIFIED live that members
match our DB on `memberUuid` (76/76) and investigators (no memberUuid) on `id` (17/17) — so
`memberUuid or id`.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from covenant_path.report import CovenantPathMember, NEEDS_PROFILE


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


def _details_subtree(p: dict, name_by_uuid: dict[str, str]) -> dict:
    """The rich progress-only subtree for the member view, in our canonical `details` shape — sourced
    from Member Tools instead of the one-work details endpoint. Profile-sourced sub-keys (callings,
    ministering, templeOrdinances) are left for the /mlt merge; here we fill the PROGRESS sub-keys.
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
    return {
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


def adapt_person(p: dict, kind: str, unit_name_by_number: dict[int, str],
                 name_by_uuid: dict[str, str], birth_by_uuid: dict[str, str] | None = None) -> CovenantPathMember:
    """One Member Tools covenant-path person → CovenantPathMember. Covenant-path PROGRESS fields are
    filled from the bulk payload; PROFILE fields use the NEEDS_PROFILE sentinel so the /mlt merge (in
    covenant_path.report) fills them from the reliable cluster — preserving the existing behaviour.

    EXCEPTION (#data-gap): birth_date is now ALSO read from the bulk payload when present (the person
    record, else the household roster) so age-gated milestones/eligibility survive a dead LCR session.
    It stays None when the payload lacks it → the /mlt merge fills it as before (no regression)."""
    unum = p.get("unitNumber")
    friend_uuids = _friend_uuids(p)
    friend_names = [name_by_uuid[u] for u in friend_uuids if name_by_uuid.get(u)]
    uuid = _person_uuid(p)
    birth = _birth_date(p) or ((birth_by_uuid or {}).get(uuid) if uuid else None)
    return CovenantPathMember(
        name=_name(p),
        unit=unit_name_by_number.get(int(unum)) if unum is not None else None,
        unit_number=int(unum) if unum is not None else None,
        person_uuid=_person_uuid(p),
        kind=kind,
        sex=_sex(p),
        # covenant-path PROGRESS (from Member Tools — the data we're rescuing from the fragile cluster)
        baptism_date=p.get("confirmationDate") or NEEDS_PROFILE,
        baptism_goal_date=p.get("baptismGoalDate"),
        friends="Yes" if friend_uuids else "No",   # friends are uuid refs — count the array, not names
        friends_count=len(friend_uuids),
        friends_summary=", ".join(friend_names) or None,
        weeks_since_last_attendance=_weeks_since_attendance(p.get("sacramentAttendance")),
        details=_details_subtree(p, name_by_uuid),
        # birth_date: rescued from the bulk payload when present (else None → /mlt merge, as before).
        birth_date=birth,
        # PROFILE-sourced fields — left for the /mlt merge (reliable cluster), exactly as before.
        aaronic_priesthood=NEEDS_PROFILE,
        melchizedek_priesthood=NEEDS_PROFILE,
        calling=NEEDS_PROFILE,
        ministering_brothers_sisters=NEEDS_PROFILE,
        ministering_assignment=NEEDS_PROFILE,
        temple_recommend=NEEDS_PROFILE,
        patriarchal_blessing=NEEDS_PROFILE,
        living_ordinance=NEEDS_PROFILE,
        membership_duration=None,
    )


# Which top-level array maps to which `kind` (the app's being-taught vs new-members split).
_ARRAYS = {
    "covenantPathInvestigators": "investigator",
    "covenantPathMembers": "new_member",
    "covenantPathReturningMembers": "returning",
}


def adapt_sync(payload: dict, include_returning: bool = True) -> list[CovenantPathMember]:
    """The whole /api/v5/sync payload → CovenantPathMember rows (covenant-path progress filled; the
    profile fields await the /mlt merge). De-dupes by person_uuid (members can appear under multiple
    arrays); a real person_uuid is required (else the DB upsert key is meaningless)."""
    units = unit_names(payload)
    name_by_uuid = _name_index(payload)
    birth_by_uuid = _birth_index(payload)
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
            out.append(adapt_person(p, kind, units, name_by_uuid, birth_by_uuid))
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
