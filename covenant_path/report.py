"""
Stake-level covenant-path aggregator.

Loops over every unit in the stake, pulls each unit's covenant-path "new member"
list (LCR one-work progress record), enriches each person with the per-member
details + member-list birth date, and assembles one stake-wide dataset of the
covenant-path tracking fields.

Run:
    python -m covenant_path.report          # all new members, all units -> output/
    python -m covenant_path.report --include-returning
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from lcr_client import LcrClient
from lcr_client.access import covenant_path_access
from lcr_client.logging_setup import dump_debug, get_logger
from lcr_client.member_profile import ProfileNotFound, profile_fields
# Shared, pure eligibility helpers (same rules the app + mailer use) — to gate priesthood display
# to eligible people (N/A for ineligible), matching the reference sheet.
from backend.milestones import is_at_least_now, member_one_year, turns_at_least
from covenant_path.profile_cache import ProfileCache

logger = get_logger()

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"
NA = "N/A"
NEEDS_PROFILE = "needs-profile-api"
BLOCKED = "blocked: insufficient calling access"

# covenant-path fields that come from the member-profile server actions, so they
# share the "menu.view.member.profiles" access gate.
_PROFILE_GATED_FIELDS = (
    "baptism_date", "temple_recommend", "patriarchal_blessing", "ministering_assignment",
)

# Field-gap provenance (#data-gap): which sentinel-able fields the RELIABLE Member Tools bulk payload
# can supply vs which can ONLY come from the per-member LCR profile (so when one is still a sentinel
# after a sync, we can say WHY). RESCUED = filled by membertools_adapter from /api/v5/sync (the org +
# directory + recommend roster); PROFILE_ONLY = genuinely absent from the bulk payload — only the LCR
# profile fetch (a LIVE LCR session) can fill them, so they go blank in steady state when the session
# is dead. As of 2026-06-13, priesthood/endowment/temple-recommend ALSO rescue from the bulk payload
# (the directory carries the priesthood office + ordinances; the unit-wide roster carries recommends),
# leaving patriarchal_blessing as the ONLY genuinely-profile-only field.
_BULK_RESCUED_FIELDS = (
    "baptism_date", "birth_date", "calling", "sex",
    "ministering_brothers_sisters", "ministering_assignment",
    "aaronic_priesthood", "melchizedek_priesthood", "temple_recommend", "living_ordinance",
)
_PROFILE_ONLY_FIELDS = (
    "patriarchal_blessing",
)


# --- field parsing -----------------------------------------------------------

def parse_priesthood(ordinations: list[str] | None) -> tuple[str, str]:
    """Map LCR priesthoodOrdinations strings to (aaronic, melchizedek) Yes/No/N/A."""
    text = " | ".join(ordinations or [])
    if "Ordained Elder" in text or "Ordained High Priest" in text:
        return ("Yes", "Yes")
    if "Eligible to receive Melchizedek Priesthood" in text:
        return ("Yes", "No")
    if any(o in text for o in ("Ordained Priest", "Ordained Teacher", "Ordained Deacon")):
        return ("Yes", "No")
    if "Eligible to receive Aaronic Priesthood" in text:
        return ("No", NA)
    return (NA, NA)


# LCR currentPriesthoodOfficeType -> (aaronic, melchizedek). Melchizedek offices imply the holder
# also received the Aaronic Priesthood. This is the AUTHORITATIVE priesthood source (the per-member
# profile record); the sparse one-work progress record's priesthoodOrdinations is empty for most.
_MELCH_OFFICES = {"ELDER", "HIGH_PRIEST", "BISHOP", "SEVENTY", "PATRIARCH", "APOSTLE"}
_AARONIC_OFFICES = {"DEACON", "TEACHER", "PRIEST"}


def priesthood_from_office(office: str | None) -> tuple[str, str]:
    o = (office or "").upper().replace(" ", "_").replace("-", "_")
    if o in _MELCH_OFFICES:
        return ("Yes", "Yes")
    if o in _AARONIC_OFFICES:
        return ("Yes", "No")
    return ("No", "No")  # profile fetched, no office -> genuinely no priesthood (eligibility gates display)


def parse_endowment(temple_ordinances: list[str] | None) -> str:
    """living_ordinance = received temple endowment."""
    text = " | ".join(temple_ordinances or [])
    if not text:
        return NA
    if "Not yet endowed" in text:
        return "No"
    if "endowed" in text.lower() or "Endowment" in text:
        return "Yes"
    return NA


def yes_no(present: bool) -> str:
    return "Yes" if present else "No"


# The two LCR "Temple Ordinances and Experiences" new-member commitments we promote to tracked
# covenant-path fields. Matched by substring (case-insensitive) so minor LCR label tweaks
# ("Prepare a Family Name for the Temple" / "Perform Baptisms for Deceased Ancestors") don't break.
_FAMILY_NAME_NEEDLE = "family name"
_TEMPLE_VISIT_NEEDLE = "baptisms for deceased"


def parse_temple_experiences(commitments: list | None) -> tuple[str, str]:
    """(family_name_prepared, first_temple_visit) Yes/No from a commitments list.
    family_name = the 'Prepare a Family Name for the Temple' commitment is being kept;
    first_temple_visit = 'Perform Baptisms for Deceased Ancestors' (a proxy-baptism trip IS the
    first temple visit for a new member). Absent commitment -> 'No' (LCR tracks it unchecked).

    ONE parser for BOTH payload shapes (the source-of-truth rule): the one-work `details` record uses
    {name, isKeeping}; the Member Tools bulk /api/v5/sync `otherCommitments` uses {title, interested}
    — same milestones, different field names. (2026-06-13: the bulk path was leaving these two fields
    as the NEEDS_PROFILE sentinel because it only knew the one-work key names — the Green Level Ward
    restore surfaced it.)"""
    family = temple = False
    for c in commitments or []:
        name = (c.get("name") or c.get("title") or "").lower()
        kept = c.get("isKeeping")
        done = bool(kept if kept is not None else c.get("interested"))
        if _FAMILY_NAME_NEEDLE in name:
            family = family or done
        elif _TEMPLE_VISIT_NEEDLE in name:
            temple = temple or done
    return (yes_no(family), yes_no(temple))


def _progress_subtree(d: dict) -> dict:
    """The covenant-path *progress* fields from a one-work details record, shaped for the
    rich member view (sacrament dots, friends, lessons, ministering, commitments).

    Deliberately drops contact PII — phoneNumbers / emailAddresses / socialMediaAccounts /
    contactInformation are NOT included, so none of that lands in Supabase.
    """
    def names(lst) -> list[str]:
        return [p.get("name") for p in (lst or []) if p.get("name")]

    def outbound(assigns) -> list[str]:
        out: list[str] = []
        for a in assigns or []:
            out += [x.get("name") for x in (a.get("assignments") or []) if x.get("name")]
        return out

    def commitments(lst) -> list[dict]:
        return [{"name": c.get("name"), "done": bool(c.get("isKeeping"))}
                for c in (lst or []) if c.get("name")]

    m = d.get("ministering") or {}
    return {
        "memberSince": d.get("memberSinceDisplayString"),
        "baptismGoalDate": d.get("baptismGoalDateString"),
        "firstLesson": d.get("firstLessonString"),
        "nextScheduledEvent": d.get("nextScheduledEventDateString"),
        "weeksSinceLastAttendance": d.get("weeksSinceLastAttendance"),
        "sacramentMissed": d.get("sacramentMeetingMessage"),
        "sacrament": [
            {"label": s.get("dateDisplay"), "attended": bool(s.get("attended")),
             "date": s.get("dateString") or s.get("date")}
            for s in (d.get("sacramentMeetingAttendanceList") or [])
        ],
        "friends": [
            {"name": f.get("name"), "unit": f.get("unitName"), "inStake": bool(f.get("inParentUnit"))}
            for f in (d.get("friends") or []) if f.get("name")
        ],
        "priesthoodOrdinations": list(d.get("priesthoodOrdinations") or []),
        "callings": list(d.get("callings") or []),
        "ministeringBrothers": names(m.get("ministeringBrothers")),
        "ministeringSisters": names(m.get("ministeringSisters")),
        "ministeringAssignments": outbound(m.get("ministeringBrothersAssignments"))
        + outbound(m.get("ministeringSistersAssignments")),
        "templeOrdinances": list(d.get("templeOrdinances") or []),
        "templeExperiences": commitments(d.get("newMemberOtherCommitments")),
        "lessons": [
            {
                "name": le.get("name"),
                "taught": le.get("numberTaughtDisplayString"),
                "principles": [
                    {"name": p.get("name"), "memberPresent": bool(p.get("memberPresent")),
                     "taughtLevel": p.get("taughtLevel")}
                    for p in (le.get("principles") or [])
                ],
            }
            for le in (d.get("lessons") or [])
        ],
        "selfReliance": commitments(d.get("selfRelianceCourses")),
        "tags": [(t.get("tagString") or {}).get("string")
                 for t in (d.get("tags") or []) if (t.get("tagString") or {}).get("string")],
        "cmisId": d.get("cmisId"),  # avatar/{cmisId} for the later photo pipeline
    }


# --- model -------------------------------------------------------------------

@dataclass
class CovenantPathMember:
    name: str | None
    unit: str | None
    baptism_date: str  # exact date not in covenant-path API
    birth_date: str | None
    friends: str
    aaronic_priesthood: str
    melchizedek_priesthood: str
    calling: str
    ministering_brothers_sisters: str
    ministering_assignment: str
    temple_recommend: str
    patriarchal_blessing: str
    living_ordinance: str
    # useful covenant-path extras the report exposes
    membership_duration: str | None
    weeks_since_last_attendance: Any | None
    baptism_goal_date: str | None
    friends_summary: str | None
    sex: str | None
    person_uuid: str | None = field(default=None)
    unit_number: int | None = field(default=None)  # stable key for DB unit mapping
    # 'new_member' (baptized), 'investigator' (being taught — has a planned baptism goal date),
    # or 'returning'. Drives the app's "being taught" vs "new members" split.
    kind: str = field(default="new_member")
    # full progress-only subtree (sacrament, friends, lessons, ministering, commitments)
    # for the rich member view — see _progress_subtree. None if details fetch failed.
    details: dict | None = field(default=None)
    # number of friends recorded in LCR (len of the friends array); None when this run
    # couldn't determine it (so the merge-upsert preserves the last-good count).
    friends_count: int | None = field(default=None)
    # Temple Ordinances and Experiences commitments, promoted to tracked fields: a prepared family
    # name (genealogy) and a first temple visit (proxy baptisms). Sentinel when details didn't fetch.
    family_name_prepared: str = field(default=NEEDS_PROFILE)
    first_temple_visit: str = field(default=NEEDS_PROFILE)


# --- build -------------------------------------------------------------------

def _details_with_retry(client: LcrClient, person_id: str, cmis_id: Any, attempts: int = 3) -> dict | None:
    """Fetch one-work/details (the rich subtree: friends NAMES, sacrament, lessons, ministering).
    This endpoint is in the same slow/flaky 500 family as progress-record, and friend NAMES come
    ONLY from here (the progress-record `friends` array carries no name key). It's called once per
    person (128+/run), so it gets a measured TRANSIENT-only retry (exp backoff + jitter via the
    shared http_util) — rather than progress-record's heavier budget — to stay inside the per-stake
    job timeout. A permanent 404 (route gone) is NOT retried; a transient 500 (the diagnostics'
    11/79 details errors) IS. NOTE: when LCR's details endpoint is fully down for ALL people no
    retry can conjure data — this only recovers transient/overloaded 500s. Returns None after all
    attempts (caller counts details_missing; the member is still assembled from the progress record,
    never crashing)."""
    from lcr_client import http_util
    return http_util.retry_call(
        lambda: client.progress_details(person_id, cmis_id),
        attempts=attempts, base_delay=1.0, max_total=30.0,
        label=f"progress_details {str(person_id)[:8]}",
    )


def _retry(fn, attempts: int = 3, delay: float = 2.0, label: str = ""):
    """Retry a call on TRANSIENT failures (LCR occasionally 500s). Returns None if all fail.

    Delegates to the shared http_util.retry_call so the transient-vs-permanent classification is
    uniform across endpoints: AuthExpiredError propagates (handled with one relogin in LcrSession);
    a flaky 5xx/timeout is retried with exp backoff + jitter (so one flaky unit doesn't fail the
    whole run); a deterministic 404 (route gone) is NOT retried (no point hammering a dead route)."""
    from lcr_client import http_util
    return http_util.retry_call(fn, attempts=attempts, base_delay=delay,
                                max_total=max(60.0, delay * attempts * 4), label=label)


def _build_member_maps(client: LcrClient, unit_number: int) -> dict[str, dict]:
    """uuid -> {'birth': display, 'sex': 'M'/'F'} from the member list — the AUTHORITATIVE source
    for sex (the one-work progress record has no sex, which broke all gender/priesthood eligibility)."""
    out: dict[str, dict] = {}
    for m in client.member_list(unit_number):
        birth = (m.raw.get("birth") or {}).get("date") or {}
        display = birth.get("display")
        sex = m.raw.get("sex")
        for key in (m.raw.get("personUuid"), m.raw.get("uuid")):
            if not key:
                continue
            info = out.setdefault(key, {})
            if display:
                info["birth"] = display
            if sex:
                info["sex"] = sex
    return out


def _friend_count(person_raw: dict, d: dict) -> int | None:
    """Number of friends in the church for a new member. Prefer the explicit names list from the
    one-work *details* endpoint when we have it; otherwise fall back to the count display string
    (`numberOfFriendsDisplayString`) carried by the one-work *progress record*. That fallback
    matters because the details endpoint is frequently down (the "no number of friends" bug) while
    the progress record — where the count comes from — keeps working, so the number still shows."""
    fr = d.get("friends")
    if isinstance(fr, list):
        return len(fr)
    s = d.get("numberOfFriendsDisplayString") or person_raw.get("numberOfFriendsDisplayString")
    if s is not None:
        m = re.search(r"\d+", str(s))
        if m:
            return int(m.group())
    return None


def _assemble(person_raw: dict, details: dict | None, unit_name: str, birth: str | None,
              kind: str = "new_member") -> CovenantPathMember:
    d = details or person_raw
    # Priesthood, calling, and endowment live in the member PROFILE. Without it the bare progress
    # record lacks those keys — emit NEEDS_PROFILE (not a false "N/A"/"No"/empty) so a no-profile or
    # partial run is PRESERVED by the merge-upsert (backend/db.upsert_members) instead of clobbering
    # good data. (Root cause of the "priesthood/calling blank in app, right in sheet" bug.)
    def _has(k: str) -> bool:
        return details is not None or k in d
    if _has("priesthoodOrdinations"):
        aaronic, melch = parse_priesthood(d.get("priesthoodOrdinations"))
    else:
        aaronic = melch = NEEDS_PROFILE
    calling = yes_no(bool(d.get("callings"))) if _has("callings") else NEEDS_PROFILE
    living = parse_endowment(d.get("templeOrdinances")) if _has("templeOrdinances") else NEEDS_PROFILE
    if _has("newMemberOtherCommitments"):
        family_name, temple_visit = parse_temple_experiences(d.get("newMemberOtherCommitments"))
    else:  # details didn't fetch — sentinel so the merge-upsert preserves last-good
        family_name = temple_visit = NEEDS_PROFILE
    ministering = d.get("ministering") or {}
    has_ministers = bool(ministering.get("ministeringBrothers") or ministering.get("ministeringSisters"))
    friend_count = _friend_count(person_raw, d)
    return CovenantPathMember(
        name=d.get("name") or person_raw.get("name"),
        unit=unit_name,
        baptism_date=NEEDS_PROFILE,
        birth_date=birth,
        # "Yes" if the details list says so OR the progress-record count is positive (keeps the flag
        # consistent with friends_count when details is down but the count came through).
        friends=yes_no(bool(d.get("friends")) or bool(friend_count)),
        friends_count=friend_count,
        aaronic_priesthood=aaronic,
        melchizedek_priesthood=melch,
        calling=calling,
        ministering_brothers_sisters=yes_no(has_ministers),
        ministering_assignment=NEEDS_PROFILE,
        temple_recommend=NEEDS_PROFILE,
        patriarchal_blessing=NEEDS_PROFILE,
        living_ordinance=living,
        membership_duration=d.get("memberSinceDisplayString") or person_raw.get("memberSinceDisplayString"),
        weeks_since_last_attendance=d.get("weeksSinceLastAttendance"),
        baptism_goal_date=d.get("baptismGoalDateString") or person_raw.get("baptismGoalDateString"),
        friends_summary=d.get("numberOfFriendsDisplayString") or person_raw.get("numberOfFriendsDisplayString"),
        sex=d.get("sex"),
        person_uuid=person_raw.get("personUuid") or person_raw.get("id"),
        kind=kind,
        family_name_prepared=family_name,
        first_temple_visit=temple_visit,
        details=_progress_subtree(d),
    )


def _apply_profile(member: CovenantPathMember, prof: dict) -> None:
    """Fill the profile-sourced fields from the AUTHORITATIVE per-member profile record. Priesthood
    comes from priesthood_office here (the one-work record's priesthoodOrdinations is empty for most
    members — the root cause of the priesthood discrepancy). calling / has-ministers are likewise
    overridden from the profile when it supplies them."""
    if prof.get("baptism_date"):
        member.baptism_date = prof["baptism_date"]
    if prof.get("temple_recommend"):
        member.temple_recommend = prof["temple_recommend"]
    if prof.get("patriarchal_blessing"):
        member.patriarchal_blessing = prof["patriarchal_blessing"]
    # The profile's ENDOWMENT ordinance date is authoritative — the one-work details endpoint often
    # lacks templeOrdinances, leaving living_ordinance derived as "No". A real endowment date = endowed.
    if prof.get("endowment_date"):
        member.living_ordinance = "Yes"
    if prof.get("ministering_assignment"):
        member.ministering_assignment = prof["ministering_assignment"]
    if not member.birth_date and prof.get("birth_date"):
        member.birth_date = prof["birth_date"]
    if prof.get("sex"):  # profile record is authoritative for sex (member list was unreliable)
        member.sex = prof["sex"]
    # Priesthood from the profile's office (authoritative). Gate the DISPLAYED value to ELIGIBLE
    # people — N/A for females / under-age / (for Melch) <1yr members — matching the reference
    # sheet, where ineligible rows show N/A rather than a misleading "No".
    if "priesthood_office" in prof:
        a, mel = priesthood_from_office(prof.get("priesthood_office"))
        em = {"sex": member.sex, "birth_date": member.birth_date, "baptism_date": member.baptism_date}
        male = member.sex == "M"
        member.aaronic_priesthood = a if (male and turns_at_least(em, 12)) else NA
        member.melchizedek_priesthood = (
            mel if (male and is_at_least_now(em, 18) and member_one_year(em)) else NA)
    # Endowment eligibility: a temple endowment is only possible for adults (18+) who've been members
    # ~1 year. Gate an ineligible member's "No" (not-yet-endowed) to N/A — "No" misleads (they can't be
    # endowed yet), matching the reference sheet + the priesthood gates above. A genuine "Yes" is kept.
    em_e = {"sex": member.sex, "birth_date": member.birth_date, "baptism_date": member.baptism_date}
    if member.living_ordinance == "No" and not (is_at_least_now(em_e, 18) and member_one_year(em_e)):
        member.living_ordinance = NA
    # First temple visit (proxy baptisms) + family name: only meaningful from the year someone turns
    # 12 (limited-use recommend age — same by-year rule as the Aaronic gate). An ineligible "No"
    # shows as N/A (they can't go yet); a genuine "Yes" is always kept.
    if not turns_at_least(em_e, 12):
        if member.first_temple_visit == "No":
            member.first_temple_visit = NA
        if member.family_name_prepared == "No":
            member.family_name_prepared = NA
    # Calling: the profile's individualCallings (member_profile.fetch_callings) is the AUTHORITATIVE
    # per-member list. The unit org-aggregate (the calling_uuids set in build_stake_report) MISSES
    # sub-org callings like "Relief Society Service Committee Member" — members held a calling yet
    # showed "No calling" (the Terry Stoner bug, 2026-06-09). UNION the two sources: a profile "Yes"
    # always upgrades; a profile "No" only applies when the org-aggregate didn't already establish a
    # "Yes" (never downgrade a real calling — mirrors the ministering rule).
    if prof.get("calling") == "Yes":
        member.calling = "Yes"
    elif prof.get("calling") == "No" and member.calling != "Yes":
        member.calling = "No"
    # Surface the calling NAME(s) in the detail view — the profile carries the full positionName even
    # when LCR's details endpoint AND the org-aggregate came back empty for this member.
    cnames = prof.get("_calling_names")
    if cnames:
        member.details = {**(member.details or {}), "callings": cnames}
    # The profile's ministering action carries OUTBOUND assignments, not INBOUND ministers, so its
    # has-ministers is "No" even when the details endpoint DID return ministers. NEVER let it
    # DOWNGRADE a details-derived "Yes" → "No" (the bug that left the flag "No" for all 85 members
    # while 42 had minister names). Only an explicit "Yes" upgrades.
    if prof.get("ministering_brothers_sisters") == "Yes":
        member.ministering_brothers_sisters = "Yes"
    # Surface minister NAMES in the detail view when LCR's details endpoint came back empty (it
    # often does) — the ministering action carries them.
    names = prof.get("_minister_names")
    if names and not (member.details or {}).get("ministeringBrothers"):
        member.details = {**(member.details or {}), "ministeringBrothers": names}
    # The minister NAMES (from details OR the profile action) are the authoritative signal for "has
    # ministers" — keep the displayed flag consistent with what we actually have to show.
    det = member.details or {}
    if det.get("ministeringBrothers") or det.get("ministeringSisters"):
        member.ministering_brothers_sisters = "Yes"


def refresh_profile_fields(client, row: dict) -> dict:
    """Back-compat wrapper over `refresh_profile_fields_ex` — the patch only, no reason."""
    return refresh_profile_fields_ex(client, row)[0]


def refresh_profile_fields_ex(client, row: dict) -> tuple[dict, str]:
    """Live-session refresh of the profile-sourced fields for ONE member — the broker's re-auth "fill
    everything" path. Fetches the per-member /mlt profile and returns {field: value} for the gated
    fields that are currently EMPTY (None in the stored `row`) but the profile now supplies, applying
    the SAME eligibility gating the daily sync uses (`_apply_profile`). So ONE re-authorization fills
    every gap a dead-session daily sync can't reach (patriarchal is the only genuinely-profile-only
    field today, but a member missing from the bulk directory recovers the rest here too). A failure
    never clobbers a value — the patch is simply empty.

    Also returns WHY, which the caller needs to report an honest outcome (a blank patch used to be
    indistinguishable from a dead session, so a fill over members who can never be filled told the
    leader to re-authorize forever — 2026-08-30):
      'filled'       — the patch has values
      'empty'        — profile fetched fine, nothing new to write
      'no_uuid'      — no person_uuid on the row: unfetchable, and re-auth can't change that
      'not_found'    — LCR 404s this person's profile page: no record to read, permanently
      'fetch_failed' — 307/timeout/stale action id: the ONLY reason a re-auth is worth offering

    NB: family_name_prepared / first_temple_visit have NO /mlt source (only the bulk feed carries the
    commitments), so they can't be recovered here."""
    uuid = row.get("person_uuid")
    if not uuid:
        return {}, "no_uuid"
    try:
        prof = profile_fields(client.session, uuid)
    except ProfileNotFound:
        return {}, "not_found"
    except Exception:  # noqa: BLE001 — 307 / stale id / transient: leave every value untouched
        return {}, "fetch_failed"

    def _seed(f: str) -> str:
        v = row.get(f)
        return v if isinstance(v, str) and v else NEEDS_PROFILE

    member = CovenantPathMember(
        name=row.get("name"), unit=row.get("unit_name"), baptism_date=_seed("baptism_date"),
        birth_date=row.get("birth_date"), friends=_seed("friends"),
        aaronic_priesthood=_seed("aaronic_priesthood"),
        melchizedek_priesthood=_seed("melchizedek_priesthood"), calling=_seed("calling"),
        ministering_brothers_sisters=_seed("ministering_brothers_sisters"),
        ministering_assignment=_seed("ministering_assignment"),
        temple_recommend=_seed("temple_recommend"), patriarchal_blessing=_seed("patriarchal_blessing"),
        living_ordinance=_seed("living_ordinance"), membership_duration=None,
        weeks_since_last_attendance=None, baptism_goal_date=None, friends_summary=None,
        sex=row.get("sex"))
    _apply_profile(member, prof)

    out: dict = {}
    for f in ("baptism_date", "temple_recommend", "patriarchal_blessing", "ministering_assignment",
              "ministering_brothers_sisters", "calling", "aaronic_priesthood",
              "melchizedek_priesthood", "living_ordinance"):
        new = getattr(member, f, None)
        if row.get(f) is None and isinstance(new, str) and new and new not in (NEEDS_PROFILE, BLOCKED):
            out[f] = new
    return out, ("filled" if out else "empty")


# Fields that come from the member profile and must be marked access-blocked (not blanked) when
# the profile can't be fetched — the merge-upsert preserves last-good for all of these sentinels.
_BLOCK_WHEN_UNFILLED = _PROFILE_GATED_FIELDS + (
    "aaronic_priesthood", "melchizedek_priesthood", "calling", "living_ordinance",
)


def _mark_profile_blocked(member: CovenantPathMember) -> None:
    """Annotate still-unfilled profile-gated fields as access-blocked (not silently blank)."""
    for fld in _BLOCK_WHEN_UNFILLED:
        if getattr(member, fld) == NEEDS_PROFILE:
            setattr(member, fld, BLOCKED)


def _feature_allowed(access: dict, feature_key: str) -> bool:
    """Whether the runner's calling is granted a feature (matrix view; default True)."""
    for row in access.get("features", []):
        if row["feature"] == feature_key:
            return row["allowed"]
    return True


def _print_access_preflight(access: dict, with_profile: bool) -> None:
    pos = ", ".join(p["name"] for p in access.get("runner_positions", [])) or "(unknown calling)"
    logger.info("report runner: %s", pos)
    print(f"[access] running as: {pos}")
    if access.get("can_pull_all"):
        print("[access] this calling is granted all covenant-path features.")
    else:
        print("[access] features NOT granted to this calling "
              "(LCR menu matrix; API may still allow — pulls are still attempted):")
        for m in access.get("missing", []):
            who = ", ".join(m["granted_by"]) or "(no named callings)"
            extra = f" (+{m['also_unnamed_roles']} other seats)" if m.get("also_unnamed_roles") else ""
            print(f"         - {m['feature']}  ->  ask: {who}{extra}")
    if with_profile and not _feature_allowed(access, "menu.view.member.profiles"):
        print("[access] note: 'Member Profiles' not granted to this calling; profile-sourced "
              "fields (baptism, recommend, patriarchal, ministering) may come back blocked.")


def order_units_stale_first(units: list, unit_order: list[int]) -> list:
    """Reorder `units` (objects with `.unit_number`) so the OLDEST-data units come first, per
    `unit_order` (the caller's oldest-data-first unit-number list). Units NOT in `unit_order` (never
    synced) sort to the very front (rank -1); ties keep their original relative order (stable). The
    sync then refreshes the most-stale wards first, so a mid-run LCR outage leaves the least-stale
    units unfinished (they keep last-good + retry next run)."""
    rank = {n: i for i, n in enumerate(unit_order)}
    return sorted(units, key=lambda u: rank.get(u.unit_number, -1))


def build_membertools_report(
    client: LcrClient,
    *,
    access_token: str | None = None,
    refresh_token: str | None = None,
    with_profile: bool = True,
    access: dict | None = None,
    cache: "ProfileCache | None" = None,
    include_returning: bool = True,
    verbose: bool = True,
) -> tuple[list[CovenantPathMember], dict]:
    """Build the covenant-path report from the RELIABLE Member Tools bulk API instead of the fragile
    one-work cluster. ONE POST /api/v5/sync replaces the per-unit progress-record + per-person details
    fan-out; the per-member /mlt profile merge (the reliable cluster) still fills the profile fields
    (patriarchal_blessing, temple_recommend, ministering, priesthood, …) via _apply_profile, exactly
    as before. Returns (members, run_stats).

    Token: prefer an explicit `access_token`; else `refresh_token` (the stored 45-day token — the
    delegated-stake path); else a silent mint off the live Okta session in `client` (the operator's
    own sync, right after login). Raises membertools.MemberToolsError / RefreshTokenExpired up to the
    caller so it can fall back to the old path or prompt a re-auth."""
    from lcr_client import membertools
    from covenant_path.membertools_adapter import adapt_sync

    if not access_token:
        if refresh_token:
            access_token = membertools.refresh(refresh_token).get("access_token")
        else:
            access_token = membertools.mint_from_okta_session(client.session.session).get("access_token")
    if not access_token:
        raise membertools.MemberToolsError("no Member Tools access token")

    payload = membertools.fetch_sync(access_token)
    members = adapt_sync(payload, include_returning=include_returning)
    stats = {"source": "membertools", "units": 1, "units_failed": 0, "failed_units": [],
             "failed_unit_numbers": [], "members": len(members), "profile_ok": 0, "profile_cached": 0,
             "profile_blocked": 0, "profile_error": 0}
    # The stake/ward structure from the payload itself, so the sync needs NO live LCR session for the
    # stake identity (the LCR session dies within days; the 45-day Member Tools token outlives it).
    from covenant_path.membertools_adapter import (
        context_from_sync, staffing_by_unit, missionaries_by_unit)
    stats["unit_context"] = context_from_sync(payload)
    # Per-unit leadership roster for the Leadership tab (#12) — session-independent (from the bulk
    # household directory); stored on units.staffing in sync_stake, RLS-scoped by units_select.
    stats["staffing_by_unit"] = staffing_by_unit(payload)
    # Per-unit missionary COMPANIONSHIPS (#3a) — session-independent (from the bulk missionariesAssigned),
    # so the roster refreshes every sync (the old /mlt path needed a live LCR session). Keyed by unit
    # number; sync_stake maps to unit name + stores on stakes.missionaries.
    stats["missionaries_by_unit"] = missionaries_by_unit(payload)
    if verbose:
        print(f"[membertools] /api/v5/sync -> {len(members)} covenant-path members")

    if access is None:
        try:
            access = covenant_path_access(client)
        except Exception:  # noqa: BLE001 — profile merge is best-effort; sentinels survive
            access = {}
    can_profiles = _feature_allowed(access, "menu.view.member.profiles")
    profile_blocked = False
    fail_streak = 0
    for member in members:
        uuid = member.person_uuid
        if not (with_profile and uuid):
            continue
        cached = cache.get(uuid) if cache else None
        if cached is not None:
            _apply_profile(member, cached)
            stats["profile_cached"] += 1
        elif profile_blocked:
            _mark_profile_blocked(member)
            stats["profile_blocked"] += 1
        else:
            try:
                prof = profile_fields(client.session, uuid)
                _apply_profile(member, prof)
                if cache:
                    cache.put(uuid, prof)
                stats["profile_ok"] += 1
                fail_streak = 0
            except Exception as exc:  # noqa: BLE001
                stats["profile_error"] += 1
                fail_streak += 1
                # If profiles keep failing AND the calling can't reach them, stop hammering a blocked
                # endpoint and mark the rest access-blocked (mirrors build_stake_report).
                if not can_profiles and fail_streak >= 5:
                    profile_blocked = True
                    _mark_profile_blocked(member)
                # Per-member detail at DEBUG only — when the LCR session is dead EVERY member fails the
                # SAME way, and 90+ identical WARNING lines bury real problems. One summary line below
                # tells the story; raise the log level to DEBUG for the per-member cause.
                logger.debug("profile merge failed for %s: %s", str(uuid)[:8], exc)
    err = stats.get("profile_error", 0)
    if err:
        ok = stats.get("profile_ok", 0)
        logger.warning(
            "profile extras: %d/%d members enriched, %d unavailable — the LCR per-member profile fetch "
            "failed (commonly the delegated LCR session is no longer live; the covenant-path CORE still "
            "synced from the Member Tools token, and these deep-profile fields keep their last-good "
            "values). A re-authorization re-establishes the LCR session to refresh them; set logging to "
            "DEBUG for the per-member cause.", ok, ok + err, err)
    # Structured field-gap report: ONE line + ONE event saying exactly which fields are still blank and
    # WHY (rescuable-but-missing vs profile-only-and-session-dead vs access-blocked) — so a leader's
    # "ministering is blank" is answerable precisely. Stashed on stats['field_gaps'] for diagnostics.
    stake_unit = getattr(stats.get("unit_context"), "unit_number", None)
    _emit_field_gap_report(members, stats, can_profiles=can_profiles, stake=stake_unit)
    return members, stats


def build_stake_report(
    client: LcrClient,
    include_returning: bool = False,
    delay: float = 0.25,
    with_profile: bool = False,
    verbose: bool = True,
    access: dict | None = None,
    cache: ProfileCache | None = None,
    only_unit: int | None = None,
    unit_order: list[int] | None = None,
) -> list[CovenantPathMember]:
    if access is None:
        access = covenant_path_access(client)
    if verbose:
        _print_access_preflight(access, with_profile)
    can_profiles = _feature_allowed(access, "menu.view.member.profiles")
    # Fresh circuit-breaker per stake: a dead endpoint (member-list 404) latched while syncing one
    # stake must not silently skip the next stake's calls in the same long-running process.
    from lcr_client import http_util
    http_util.breaker.reset()

    ctx = client.user_context()
    units = [u for u in ctx.child_units if u.unit_number and u.type in ("WARD", "BRANCH")]
    if only_unit:  # OPS per-unit refetch (#19): re-pull just one ward/branch
        units = [u for u in units if u.unit_number == only_unit]
    elif unit_order:
        units = order_units_stale_first(units, unit_order)
    results: list[CovenantPathMember] = []
    seen_uuids: set[str] = set()

    # Attempt-then-annotate: the matrix isn't 1:1 with API access, so we always try.
    # If the calling lacks profile access AND fetches keep failing, stop hammering a
    # blocked endpoint and mark the rest as access-blocked.
    profile_blocked = False
    profile_fail_streak = 0
    stats = {"units": 0, "units_failed": 0, "failed_units": [], "failed_unit_numbers": [],
             "members": 0, "profile_ok": 0, "profile_cached": 0, "profile_blocked": 0,
             "profile_error": 0, "details_missing": 0}

    for unit in units:
        if verbose:
            print(f"[*] {unit.name} ({unit.unit_number})")
        # progress-record is LCR's slowest, flakiest endpoint (probe: ~10.8s p50, ~38% 500s under
        # load) and is the dominant cause of "unit failed" — NOT rate limiting. Be patient: more
        # attempts + longer backoff so a transient 500 doesn't lose the whole unit.
        pr = _retry(lambda u=unit: client.progress_record(u.unit_number),
                    attempts=5, delay=4.0, label=f"progress_record {unit.unit_number}")
        if pr is None:
            stats["units_failed"] += 1
            stats["failed_units"].append(unit.name)
            stats["failed_unit_numbers"].append(unit.unit_number)
            if verbose:
                print(f"    [!] skipped {unit.name}: progress-record unavailable after retries")
            continue
        # member-list currently 404s for every unit (LCR moved/removed /api/umlu/report/member-list,
        # probe-confirmed) — it only enriches sex/birth, which the profile fetch also provides, so a
        # miss degrades gracefully. One quick attempt (no point retrying a deterministic 404).
        member_maps = _retry(lambda u=unit: _build_member_maps(client, u.unit_number),
                             attempts=1, label=f"member_list {unit.unit_number}") or {}

        # has-calling BASELINE per member: whoever holds a position in the unit's org tree (the same
        # org-callings endpoint roles.py uses). This MISSES sub-org callings (Relief Society Service
        # Committee, etc.) — so it's only the BASELINE; the per-member profile action (fetch_callings)
        # is authoritative and UNIONs in via _apply_profile. None => couldn't fetch (don't override).
        calling_names: dict[str, list] = {}  # person_uuid -> [calling name, ...] for the detail view
        try:
            from backend.roles import _ward_positions
            _positions = _ward_positions(client.org_callings(unit.unit_number))
            calling_uuids: set | None = {p["person_uuid"] for p in _positions if p.get("person_uuid")}
            for p in _positions:
                if p.get("person_uuid") and p.get("calling"):
                    calling_names.setdefault(p["person_uuid"], []).append(p["calling"])
        except Exception as exc:  # noqa: BLE001
            logger.warning("org callings unavailable for %s (%s): %s", unit.name, unit.unit_number, exc)
            calling_uuids = None

        # newMemberList = baptized; investigatorList = people being taught (planned baptism
        # date in baptismGoalDateString). Tag each so the app can split the two populations.
        people = [(p, "new_member") for p in (pr.raw.get("newMemberList") or [])]
        people += [(p, "investigator") for p in (pr.raw.get("investigatorList") or [])]
        if include_returning:
            people += [(p, "returning") for p in (pr.raw.get("returningMemberList") or [])]

        # One-time PII-safe diagnostic for the calling under-count (#GH "double-check calling %"):
        # decides between two causes — (a) /mlt/api/orgs returns few callings (coverage), or (b) the
        # org-position uuids don't match the progress-record personUuids (matching). Logs counts +
        # one sample uuid from each source (uuids are opaque ids, not PII). On the next live sync,
        # check tools/output/logs: positions≈cohort but matched≈0 ⇒ uuid mismatch; positions small
        # ⇒ the orgs endpoint itself is sparse for this unit.
        if calling_uuids is not None:
            cohort_uuids = {p.get("personUuid") for p, _k in people if p.get("personUuid")}
            matched = cohort_uuids & calling_uuids
            stats["calling_positions"] = stats.get("calling_positions", 0) + len(calling_uuids)
            stats["calling_matched"] = stats.get("calling_matched", 0) + len(matched)
            if not stats.get("calling_shape_dumped"):
                stats["calling_shape_dumped"] = True
                pos_s, coh_s = next(iter(calling_uuids), None), next(iter(cohort_uuids), None)
                # logger.info → lands in the uploaded session log (dump_debug only writes to the
                # un-uploaded debug/ dir). uuids are opaque ids, not PII.
                logger.info("calling_match_shape unit=%s positions=%d cohort=%d matched=%d "
                            "pos_uuid=%s cohort_uuid=%s", unit.unit_number, len(calling_uuids),
                            len(cohort_uuids), len(matched), pos_s, coh_s)
                dump_debug("calling_match_shape", unit=unit.unit_number,
                           positions=len(calling_uuids), cohort=len(cohort_uuids),
                           matched=len(matched), position_uuid_sample=pos_s, cohort_uuid_sample=coh_s)

        for person, kind in people:
            details = _details_with_retry(client, person.get("id"), person.get("cmisId"))
            if details is None:
                stats["details_missing"] += 1
            info = member_maps.get(person.get("personUuid")) or member_maps.get(person.get("id")) or {}
            birth = info.get("birth")
            member = _assemble(person, details, unit.name, birth, kind=kind)
            member.sex = info.get("sex") or member.sex  # member list is authoritative for sex
            if calling_uuids is not None:  # org positions seed the BASELINE (profile unions the
                #                            authoritative per-member callings later, in _apply_profile)
                pu = person.get("personUuid")
                member.calling = "Yes" if (pu and pu in calling_uuids) else "No"
                # Surface the calling NAME in the detail view when LCR's details endpoint came back
                # empty (it often does) — the org positions have it.
                if pu and calling_names.get(pu) and not (member.details or {}).get("callings"):
                    member.details = {**(member.details or {}), "callings": calling_names[pu]}
            member.unit_number = unit.unit_number
            uuid = person.get("personUuid")
            if uuid:
                seen_uuids.add(uuid)
            called_api = False
            if with_profile and uuid:
                cached = cache.get(uuid) if cache else None
                if cached is not None:
                    _apply_profile(member, cached)
                    stats["profile_cached"] += 1
                elif profile_blocked:
                    _mark_profile_blocked(member)
                    stats["profile_blocked"] += 1
                else:
                    called_api = True
                    try:
                        prof = profile_fields(client.session, uuid)
                        _apply_profile(member, prof)
                        if cache:
                            cache.put(uuid, prof)
                        stats["profile_ok"] += 1
                    except Exception as exc:  # noqa: BLE001
                        stats["profile_error"] += 1
                        profile_fail_streak += 1
                        _mark_profile_blocked(member)
                        logger.warning("profile fetch failed for %s (%s): %s",
                                       member.name, uuid, exc)
                        dump_debug("report_profile_fail", name=member.name,
                                   uuid=uuid, error=str(exc), can_profiles=can_profiles)
                        if not can_profiles and profile_fail_streak >= 3:
                            profile_blocked = True
                            if verbose:
                                print("    [access] profile fetches failing and calling lacks "
                                      "'Member Profiles' access -> marking remaining as blocked.")
                        elif verbose:
                            print(f"    [!] profile fetch failed for {member.name}: {exc}")
            results.append(member)
            stats["members"] += 1
            if called_api:
                time.sleep(delay)  # only throttle when we actually hit the API

        stats["units"] += 1
        if verbose:
            print(f"    {len(people)} covenant-path members")

    if cache:
        cache.prune(seen_uuids)
        cache.save()
        stats["cache"] = cache.stats
    logger.info("report complete: %s", stats)
    access["_run_stats"] = stats
    # Defensive: don't let a uniformly-stale field (stale action id) clobber good data — sentinel it
    # so the upsert preserves last-good and freshness shows staleness.
    stats["neutralized_stale"] = _neutralize_uniform_stale(results, with_profile)
    return results


def _field_coverage(dicts: list[dict]) -> dict[str, dict[str, int]]:
    """Per profile-gated field: how many rows are filled / blocked / pending."""
    cov: dict[str, dict[str, int]] = {}
    for fld in _PROFILE_GATED_FIELDS:
        c = {"filled": 0, "blocked": 0, "pending": 0}
        for d in dicts:
            v = d.get(fld)
            if v == BLOCKED:
                c["blocked"] += 1
            elif v in (NEEDS_PROFILE, None, ""):
                c["pending"] += 1
            else:
                c["filled"] += 1
        cov[fld] = c
    return cov


def field_gap_report(rows: list["CovenantPathMember"], *, profile_merge_ran: bool,
                     can_profiles: bool = True) -> dict:
    """A STRUCTURED 'why is this field blank?' summary for a stake (#data-gap). For every field that
    CAN end up a sentinel, count how many members are still missing it and attribute a REASON, so an
    operator/Claude can answer "ministering is blank" precisely instead of guessing. Reasons:

      • "not in bulk payload (profile merge skipped)" — a PROFILE-only field (temple recommend,
        priesthood, patriarchal, endowment) while the LCR profile fetch did NOT run this sync (the
        steady-state dead-LCR-session case): genuinely unrecoverable until a re-auth.
      • "calling lacks access"                       — a profile-only field while the calling can't
        reach Member Profiles (the access-blocked, BLOCKED-sentinel case).
      • "not returned this run"                      — a RESCUABLE field (ministering/calling/birth)
        still a sentinel: the bulk payload didn't carry it for these members (e.g. their unit's
        ministering org wasn't present, or they're absent from the directory).
      • "profile not yet fetched"                    — a profile-only field still pending while the
        merge DID run (a transient per-member miss).

    Returns {"members": N, "fields": {field: {"missing": k, "reason": str}}, "worst": [field, …]} —
    empty `fields` when nothing is missing. PII-free (counts + field names only)."""
    n = len(rows)
    fields: dict[str, dict] = {}
    for fld in (*_BULK_RESCUED_FIELDS, *_PROFILE_ONLY_FIELDS):
        missing = blocked = 0
        for r in rows:
            v = getattr(r, fld, None)
            if v == BLOCKED:
                blocked += 1
                missing += 1
            elif v in (NEEDS_PROFILE, None, ""):
                missing += 1
        if not missing:
            continue
        if blocked and not can_profiles:
            reason = "calling lacks Member Profiles access"
        elif fld in _PROFILE_ONLY_FIELDS:
            reason = ("not in bulk payload + LCR profile merge skipped (session likely dead — re-auth "
                      "to refresh)" if not profile_merge_ran else "profile not yet fetched (transient)")
        else:  # a rescuable field still a sentinel
            reason = "not returned in the bulk payload this run (unit org / directory gap)"
        fields[fld] = {"missing": missing, "blocked": blocked, "reason": reason}
    worst = sorted(fields, key=lambda f: fields[f]["missing"], reverse=True)
    return {"members": n, "fields": fields, "worst": worst}


def _emit_field_gap_report(rows: list["CovenantPathMember"], stats: dict, *,
                           can_profiles: bool, stake: int | None = None,
                           correlation_id: str | None = None) -> dict:
    """Compute the field-gap report and emit it as ONE structured log line + ONE observability event
    (NOT a per-member flood). Stashes it on `stats['field_gaps']` for the diagnostics row, so an
    operator can later query exactly why a field is blank. Best-effort: never breaks the sync."""
    profile_merge_ran = stats.get("profile_ok", 0) > 0 or stats.get("profile_cached", 0) > 0
    report = field_gap_report(rows, profile_merge_ran=profile_merge_ran, can_profiles=can_profiles)
    stats["field_gaps"] = report
    gaps = report.get("fields") or {}
    # Distinct LOUD alarm for a DEGRADED bulk payload: a field that CAN be rescued from /api/v5/sync
    # showing 100% missing across a populated stake is the signature of a partial payload (a dropped
    # household directory / templeRecommendStatus sub-tree) — NOT a dead LCR session (that only blocks
    # PROFILE-only fields like patriarchal) and NOT a normal partial sync. Today it silently degrades the
    # WHOLE stake to sentinels with only a soft, mixed-in field-gap line. Surface it separately
    # (error-level + its own event + a stats key) so an operator can tell "the payload came back gutted"
    # apart from routine per-field gaps. Read-only over the already-computed counts; never writes data.
    members_n = report.get("members") or 0
    degraded = [f for f in _BULK_RESCUED_FIELDS
                if members_n >= 20 and gaps.get(f, {}).get("missing") == members_n]
    if degraded:
        stats["degraded_payload_fields"] = degraded
        logger.error(
            "DEGRADED /api/v5/sync (stake %s): %d bulk-rescuable field(s) 100%% missing across all %d "
            "members — likely a partial bulk payload (dropped directory / recommend roster), NOT a dead "
            "session; last-good preserved. Fields: %s",
            stake if stake is not None else "?", len(degraded), members_n, ", ".join(degraded))
        try:
            from backend import observability as obs
            obs.event("sync.degraded_payload", level="error", stake=stake,
                      correlation_id=correlation_id, status="degraded", members=members_n,
                      fields=degraded, message=f"{len(degraded)} bulk-rescuable field(s) 100% missing")
        except Exception as exc:  # noqa: BLE001 — observability must never break the sync
            logger.debug("degraded-payload event skipped: %s", exc)
    if gaps:
        summary = ", ".join(f"{f}={gaps[f]['missing']}/{report['members']} ({gaps[f]['reason']})"
                            for f in report["worst"])
        logger.warning("field-gap report (stake %s): %s", stake if stake is not None else "?", summary)
        try:
            from backend import observability as obs
            obs.event("sync.field_gaps", level="warning", stake=stake, correlation_id=correlation_id,
                      count=len(gaps), status="degraded",
                      message=summary[:300], fields={f: gaps[f]["missing"] for f in gaps},
                      reasons={f: gaps[f]["reason"] for f in gaps})
        except Exception as exc:  # noqa: BLE001 — observability must never break the sync
            logger.debug("field-gap event skipped: %s", exc)
    else:
        logger.info("field-gap report (stake %s): all sentinel-able fields filled", stake)
    return report


def _neutralize_uniform_stale(rows: list[CovenantPathMember], with_profile: bool) -> list[str]:
    """Defensive (#data-correctness): when a profile field is UNIFORMLY the negative value across a
    whole stake, that's the signature of a stale/failed action id — NOT real data. Converting it to
    the SENTINEL makes the upsert PRESERVE the last-good value and the per-field freshness show
    staleness, instead of clobbering good data with a wrong 'No'. Returns the neutralized fields."""
    n = len(rows)
    if not with_profile or n < 20:
        return []
    neutralized: list[str] = []
    # temple_recommend: zero Active/Expired across >=20 members ⇒ stale recommend action (converts
    # carry limited-use recommends; a whole stake with none is implausible). Don't touch an
    # already-all-sentinel field (that's access-blocked, reported elsewhere).
    recs = [m.temple_recommend for m in rows]
    if not all(v in (BLOCKED, NEEDS_PROFILE) for v in recs) and not any(v in ("Active", "Expired") for v in recs):
        for m in rows:
            if m.temple_recommend not in (BLOCKED, NEEDS_PROFILE):
                m.temple_recommend = NEEDS_PROFILE
        neutralized.append("temple_recommend")
    # calling: zero "Yes" across >=20 members ⇒ BOTH calling sources failed (a stale callings action AND
    # a sparse org-aggregate). New-member cohorts DO accrue callings (integration is the whole point —
    # Terry Stoner is a new member with one), so a whole stake with none is the stale-action signature,
    # not real data. Same preserve-last-good treatment. (Won't fire while either source yields a "Yes".)
    cals = [m.calling for m in rows]
    if not all(v in (BLOCKED, NEEDS_PROFILE) for v in cals) and not any(v == "Yes" for v in cals):
        for m in rows:
            if m.calling not in (BLOCKED, NEEDS_PROFILE):
                m.calling = NEEDS_PROFILE
        neutralized.append("calling")
    if neutralized:
        logger.warning("neutralized uniformly-stale field(s) -> sentinel (preserve last-good, show "
                       "stale): %s", neutralized)
    return neutralized


def _sanity_warnings(rows: list[CovenantPathMember], with_profile: bool) -> list[str]:
    """Flag distributions that suggest a silent failure (e.g. a stale action id).

    The data can look 'filled' while being uniformly wrong — the classic symptom of
    a rotated profile action id is EVERY member coming back with the empty value. We
    only warn above a sample size where uniformity is implausible.
    """
    warnings: list[str] = []
    n = len(rows)
    if not with_profile or n < 20:
        return warnings
    recs = [m.temple_recommend for m in rows]
    if all(v in (BLOCKED, NEEDS_PROFILE) for v in recs):
        return warnings  # access-blocked is already reported elsewhere
    active = sum(1 for v in recs if v in ("Active", "Expired"))
    if active == 0:
        warnings.append(
            f"temple_recommend is 'No' for all {n} members — the recommend action id "
            "may be stale. Verify with tools/health_check.py / re-run action discovery."
        )
    baptized = sum(1 for m in rows if m.baptism_date not in (NA, NEEDS_PROFILE, BLOCKED, None, ""))
    if baptized == 0:
        warnings.append(
            f"baptism_date is empty for all {n} members — the profile record action id "
            "may be stale."
        )
    for w in warnings:
        logger.warning("sanity: %s", w)
    return warnings


def export(rows: list[CovenantPathMember], access: dict | None = None,
           with_profile: bool = False) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    dicts = [asdict(r) for r in rows]
    (OUTPUT_DIR / "covenant_path_stake.json").write_text(
        json.dumps(dicts, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    if dicts:
        # the JSON keeps the nested `details` subtree; the CSV stays flat/human-readable.
        flat_cols = [k for k in dicts[0].keys() if k != "details"]
        with (OUTPUT_DIR / "covenant_path_stake.csv").open(
            "w", newline="", encoding="utf-8-sig"
        ) as fh:
            writer = csv.DictWriter(fh, fieldnames=flat_cols, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(dicts)
    print(f"\n[+] {len(rows)} members -> {OUTPUT_DIR}")
    print("    - covenant_path_stake.json")
    print("    - covenant_path_stake.csv")

    if access is not None:
        coverage = _field_coverage(dicts)
        warnings = _sanity_warnings(rows, with_profile)
        summary = {
            "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "runner_positions": access.get("runner_positions"),
            "role_ids": access.get("role_ids"),
            "can_pull_all": access.get("can_pull_all"),
            "features": access.get("features"),
            "missing_who_to_ask": access.get("missing"),
            "run_stats": access.get("_run_stats"),
            "field_coverage": coverage,
            "sanity_warnings": warnings,
            "total_members": len(dicts),
        }
        (OUTPUT_DIR / "covenant_path_access.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print("    - covenant_path_access.json  (access + field-coverage summary)")
        logger.info("field coverage: %s", coverage)
        blocked = [f for f, c in coverage.items() if c["blocked"]]
        if blocked:
            print(f"[access] blocked fields this run: {', '.join(blocked)} "
                  "(see covenant_path_access.json -> missing_who_to_ask)")
        for w in warnings:
            print(f"[!] SANITY: {w}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Stake-level covenant-path report")
    parser.add_argument("--include-returning", action="store_true")
    parser.add_argument("--delay", type=float, default=0.25, help="seconds between detail calls")
    parser.add_argument("--with-profile", action="store_true",
                        help="also fetch baptism date / patriarchal blessing from the member-profile "
                             "server action (pure HTTP, one extra POST per member)")
    parser.add_argument("--no-cache", action="store_true",
                        help="disable the incremental profile cache (force fresh fetch of every member)")
    parser.add_argument("--cache-max-age-days", type=float, default=7.0,
                        help="reuse cached profile fields newer than this (0 = always refresh)")
    args = parser.parse_args()

    client = LcrClient()
    access = covenant_path_access(client)
    cache = ProfileCache(max_age_days=args.cache_max_age_days, enabled=not args.no_cache)
    rows = build_stake_report(
        client,
        include_returning=args.include_returning,
        delay=args.delay,
        with_profile=args.with_profile,
        access=access,
        cache=cache,
    )
    export(rows, access=access, with_profile=args.with_profile)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
