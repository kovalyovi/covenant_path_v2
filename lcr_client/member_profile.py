"""
Member-profile data via pure HTTP (no browser).

The Member Tools profile page (/mlt) loads its data through a Next.js Server
Action: an HTTP POST to the page URL carrying a `Next-Action` header. We replay
that POST with the authenticated cookie session and parse the React-flight
response. This yields baptism date, patriarchal blessing, ordinances, and a
clean priesthood office — fields not exposed by the regular JSON APIs.

The action ids are build-specific (change when LCR redeploys the /mlt app). They
live in lcr_client.action_config (seeded by DEFAULTS, overridable by a local
config file). On a shape miss we auto-discover fresh ids (action_discovery) once
per process and retry — so the client self-heals across LCR redeploys.

Provides: member record (baptism, patriarchal, ordinances, priesthood office),
temple recommend, and outbound ministering assignment — all via pure HTTP.
"""

from __future__ import annotations

import json
import re
from urllib.parse import quote

from lcr_client import action_config
from lcr_client.hosts import LCR_BASE
from lcr_client.logging_setup import dump_debug, get_logger

logger = get_logger()

# Defaults kept as module attrs for convenience/back-compat; live values come
# from action_config.load() at call time (so auto-discovered ids take effect).
PROFILE_ACTION_ID = action_config.DEFAULTS["record"]
RECOMMEND_ACTION_ID = action_config.DEFAULTS["recommend"]
MINISTERING_ACTION_ID = action_config.DEFAULTS["ministering"]
PROFILE_URL = LCR_BASE + "/mlt/records/member-profile/{uuid}?lang=eng"

_ROW_RE = re.compile(r"^[0-9a-f]+:(.*)$")
_HEAL_ATTEMPTED = False


def _heal_once(session, uuid: str) -> None:
    """Run action-id auto-discovery at most once per process."""
    global _HEAL_ATTEMPTED
    if _HEAL_ATTEMPTED:
        return
    _HEAL_ATTEMPTED = True
    try:
        from lcr_client import action_discovery
        logger.warning("profile action returned no data — attempting action-id auto-discovery")
        action_discovery.heal(session, uuid)
    except Exception as exc:  # noqa: BLE001
        logger.error(f"action-id discovery failed: {exc}")


def _state_tree(uuid: str) -> str:
    tree = ["", {"children": ["records", {"children": ["member-profile", {
        "children": [["id", uuid, "d"], {"children": ["__PAGE__", {}, None, None]},
                     None, None]}, None, None]}, None, None]}, None, None, True]
    return quote(json.dumps(tree, separators=(",", ":")))


def flight_objects(text: str) -> list:
    """Parse every JSON object/array row out of a React-flight response."""
    out = []
    for line in text.split("\n"):
        m = _ROW_RE.match(line)
        if not m:
            continue
        payload = m.group(1)
        if not (payload.startswith("{") or payload.startswith("[")):
            continue
        try:
            out.append(json.loads(payload))
        except json.JSONDecodeError:
            continue
    return out


def _find(objs: list, *keys: str) -> dict | None:
    """Return the first dict row that contains all given keys."""
    for o in objs:
        if isinstance(o, dict) and all(k in o for k in keys):
            return o
    return None


def parse_flight_record(text: str) -> dict | None:
    """Find the member-record object in a React-flight response."""
    return _find(flight_objects(text), "uuid", "ordinances")


def _ordinance_date(record: dict, type_: str) -> str | None:
    for o in record.get("ordinances") or []:
        if o.get("type") == type_:
            return o.get("dateDisplay")
    return None


_dumped_record_shape = False


def _as_list(*vals):
    for v in vals:
        if isinstance(v, list):
            return v
    return None


def extract_fields(record: dict) -> dict:
    """Pull the covenant-path-relevant fields out of the raw member record. Priesthood, callings,
    and received ministering come from HERE (the authoritative per-member profile) — the one-work
    progress record is sparse for these. A one-time PII-safe shape dump (keys only) lands in
    tools/output/logs so the exact calling/ministering keys can be confirmed from a real sync."""
    global _dumped_record_shape
    if not _dumped_record_shape:
        _dumped_record_shape = True
        try:
            dump_debug("profile_record_shape", keys=sorted(record.keys()),
                       priesthood_office=record.get("currentPriesthoodOfficeType"))
        except Exception:  # noqa: BLE001
            pass

    birth = record.get("birth") or {}
    out = {
        "birth_date": birth.get("dateDisplay"),
        "baptism_date": _ordinance_date(record, "BAPTISM"),
        "confirmation_date": _ordinance_date(record, "CONFIRMATION"),
        "endowment_date": _ordinance_date(record, "ENDOWMENT"),
        "sealed_to_parents_date": _ordinance_date(record, "SEALING_TO_PARENTS"),
        "patriarchal_blessing": "Yes" if record.get("hasPatriarchalBlessing") else "No",
        "priesthood_office": record.get("currentPriesthoodOfficeType"),
        "sex": record.get("sex"),  # authoritative ("M"/"F") — the member-list field is unreliable
    }
    # Callings: a non-empty current-callings/positions list -> "Yes" (best-effort across the known
    # record shapes; if none match, the shape dump above reveals the real key and we map it).
    callings = _as_list(record.get("callings"), record.get("positions"),
                        record.get("currentCallings"), record.get("memberCallings"))
    if callings is not None:
        out["calling"] = "Yes" if callings else "No"
    # Received ministering (who ministers TO this member).
    minw = record.get("ministering") or {}
    recv = _as_list(minw.get("ministeringBrothers"), minw.get("ministeringSisters"),
                    record.get("ministeringBrothers"), record.get("ministeringSisters"),
                    record.get("assignedMinisteringBrothers"))
    if recv is not None:
        out["ministering_brothers_sisters"] = "Yes" if recv else "No"
    return out


def call_action(session, person_uuid: str, action_id: str, args: list) -> list:
    """POST a member-profile server action and return the parsed flight rows.

    The profile server actions are the SOURCE of the four parity fields (baptism_date,
    temple_recommend, patriarchal_blessing, ministering_assignment). LCR's /mlt app is in the same
    slow/flaky 500 family as the one-work endpoints, so a transient overload on this POST used to
    fail the member's whole profile fetch → those four fields fell to BLOCKED (the 54/69 parity in
    the diagnostics). We now (a) RECORD the POST in metrics (it was invisible in the endpoint report
    because it bypassed get_json) and (b) RETRY transient 5xx/timeouts with backoff so a flaky 500
    doesn't strand the member. A deterministic 404 (action route gone) is NOT retried."""
    import time as _t

    from lcr_client import http_util, metrics

    url = PROFILE_URL.format(uuid=person_uuid)
    headers = {
        "Accept": "text/x-component",
        "Content-Type": "text/plain;charset=UTF-8",
        "Next-Action": action_id,
        "Next-Router-State-Tree": _state_tree(person_uuid),
        "Origin": LCR_BASE,
        "Referer": url,
    }
    body = json.dumps(args, separators=(",", ":"))

    def _post():
        t0 = _t.perf_counter()
        try:
            resp = session.session.post(
                url, headers=headers, data=body, timeout=60, allow_redirects=False,
            )
        except Exception as exc:  # noqa: BLE001 — record timeouts/conn errors too
            metrics.record(url, 0, (_t.perf_counter() - t0) * 1000, error=type(exc).__name__)
            raise
        metrics.record(url, resp.status_code, (_t.perf_counter() - t0) * 1000)
        # A 5xx (or a redirect to the login host) means a degraded/expired server response — surface
        # it as an error so retry_call can back off and retry the transient ones. raise_for_status
        # raises requests.HTTPError carrying resp.status_code, which http_util classifies.
        resp.raise_for_status()
        return flight_objects(resp.text)

    rows = http_util.retry_call(
        _post, attempts=3, base_delay=1.0, max_total=45.0,
        label=f"profile_action {action_id[:8]}",
    )
    return rows or []


def fetch_member_profile(session, person_uuid: str) -> dict:
    """Replay the profile record action and return the raw member record dict."""
    def call():
        return _find(call_action(session, person_uuid, action_config.load()["record"],
                                 [person_uuid, "eng"]), "uuid", "ordinances")

    record = call()
    if record is None:
        _heal_once(session, person_uuid)
        record = call()
    if record is None:
        dump_debug("profile_record_miss", uuid=person_uuid, action=action_config.load()["record"])
        raise RuntimeError(
            "No member record in profile response. Action id stale and auto-discovery "
            "failed, or session expired — check tools/output/logs and debug."
        )
    return record


def fetch_patriarchal(session, person_uuid: str) -> str | None:
    """Patriarchal blessing ONLY — the one covenant-path field absent from the bulk `/api/v5/sync`,
    so it can only come from this LIVE-session `/mlt` record action. Returns "Yes"/"No" (the same raw
    flag `extract_fields` derives), or **None** when it can't be read — a member with no record, or the
    common case where the session isn't authenticated for `/mlt` (an aged delegated credential gets a
    307 redirect to login → no flight record). The caller treats None as "leave the stored value
    untouched", so a failed fetch never clobbers a good value. Lean: one action, not the 4-action
    `profile_fields`."""
    try:
        record = fetch_member_profile(session, person_uuid)
    except Exception:  # noqa: BLE001 — 307/no-record/transient: caller leaves the value as-is
        return None
    return "Yes" if record.get("hasPatriarchalBlessing") else "No"


def fetch_recommend(session, person_uuid: str) -> dict:
    """Temple recommend: {status, expirationDateDisplay, isLimitedUse} or {} if none."""
    def call():
        # the recommend action always returns the `hasNewRecommendInProcess` key,
        # even when the member has no recommend — use it to detect a valid action.
        return _find(call_action(session, person_uuid, action_config.load()["recommend"],
                                 [person_uuid]), "hasNewRecommendInProcess")

    obj = call()
    if obj is None:
        # Often LEGITIMATE, not an error: LCR's recommend server action throws
        # (returns an error/digest flight object) for members who simply have no
        # recommend (e.g. new converts, minors) -> we map that to "No". We do NOT
        # self-heal here: the record action (fetch_member_profile) is the reliable
        # canary for a stale build; healing on a no-recommend member is a false alarm
        # (it triggered a needless Playwright run in CI). A genuinely stale recommend
        # id surfaces as a uniform "No" across everyone -> report sanity check flags it.
        logger.debug("no recommend data for %s (no recommend, or stale action id)", person_uuid)
        return {}
    return obj.get("recommend") or {}


def fetch_ministering(session, person_uuid: str) -> dict:
    """Outbound ministering: whether this person is assigned as a minister."""
    def call():
        objs = call_action(session, person_uuid, action_config.load()["ministering"], [person_uuid])
        return _find(objs, "ministeringBrothersAssignments") or _find(objs, "ministeringSistersAssignments")

    # no self-heal here either — a no-assignment member legitimately returns nothing;
    # the record action is the canary for a stale build (see fetch_recommend).
    obj = call() or {}
    companionships = (obj.get("ministeringBrothersAssignments") or []) + \
                     (obj.get("ministeringSistersAssignments") or [])
    has_outbound = any(c.get("assignments") for c in companionships)
    # Inbound: who is assigned to minister TO this member (the "has ministers" field). Same response.
    inbound = (obj.get("ministeringBrothers") or []) + (obj.get("ministeringSisters") or [])
    global _dumped_min_shape
    if inbound and not _dumped_min_shape:
        _dumped_min_shape = True
        s = inbound[0]
        dump_debug("ministering_inbound_shape",
                   shape=sorted(s.keys()) if isinstance(s, dict) else type(s).__name__)
    names = [n for n in (_minister_name(m) for m in inbound) if n]
    return {"has_assignment": has_outbound, "has_ministers": bool(inbound),
            "minister_names": names, "companionships": companionships, "raw": obj}


_dumped_min_shape = False


def _minister_name(m) -> str | None:
    """Best-effort 'Last, First' from an inbound minister record (the exact key set lands in the
    one-time ministering_inbound_shape dump so we can tighten this)."""
    if isinstance(m, str):
        return m or None
    if not isinstance(m, dict):
        return None
    for k in ("name", "displayName", "preferredName", "fullName", "spokenName"):
        if m.get(k):
            return str(m[k])
    sur = m.get("surname") or m.get("lastName")
    giv = m.get("givenName") or m.get("firstName")
    return f"{sur}, {giv}".strip(", ") if (sur or giv) else None


def _recommend_label(recommend: dict) -> str:
    status = (recommend or {}).get("status")
    if status == "ACTIVE":
        return "Active"
    if status == "EXPIRED":
        return "Expired"
    return "No"


_dumped_calling_shape = False


def fetch_callings(session, person_uuid: str) -> dict:
    """Per-member callings via the dedicated profile action (returns `individualCallings`). This is the
    AUTHORITATIVE calling source: the unit org-aggregate (backend.roles._ward_positions) misses sub-org
    callings like "Relief Society Service Committee Member", so members held a calling yet showed "No
    calling" (the Terry Stoner bug). Returns {has_calling, calling_names: [positionName, ...]}."""
    def call():
        return _find(call_action(session, person_uuid, action_config.load()["callings"],
                                 [person_uuid, "eng"]), "individualCallings")

    obj = call()
    if obj is None:
        # Like recommend/ministering: a no-calling member can legitimately return nothing, so we do NOT
        # self-heal here (the record action is the canary for a stale build). A genuinely stale callings
        # id surfaces as a uniform "No calling" across everyone -> report._neutralize_uniform_stale flags
        # it and the calling diagnostic logs matched=0.
        logger.debug("no callings data for %s (no calling, or stale action id)", person_uuid)
        return {"has_calling": False, "calling_names": []}
    cals = obj.get("individualCallings") or []
    global _dumped_calling_shape
    if cals and not _dumped_calling_shape:
        _dumped_calling_shape = True
        c0 = cals[0]
        dump_debug("calling_shape", shape=sorted(c0.keys()) if isinstance(c0, dict) else type(c0).__name__)
    names = [c.get("positionName") or c.get("customCallingName") or c.get("name")
             for c in cals if isinstance(c, dict)]
    names = [n for n in names if n]
    return {"has_calling": bool(cals), "calling_names": names}


def profile_fields(session, person_uuid: str) -> dict:
    """All profile-sourced covenant-path fields via the server actions. Priesthood (office) +
    received ministering ('has ministers') come from here authoritatively; calling is derived
    separately from the unit org positions (see covenant_path.report)."""
    fields = extract_fields(fetch_member_profile(session, person_uuid))
    fields["temple_recommend"] = _recommend_label(fetch_recommend(session, person_uuid))
    minw = fetch_ministering(session, person_uuid)
    fields["ministering_assignment"] = "Yes" if minw["has_assignment"] else "No"
    fields["ministering_brothers_sisters"] = "Yes" if minw["has_ministers"] else "No"
    fields["_minister_names"] = minw.get("minister_names") or []  # transient: report injects into details
    # Calling from the AUTHORITATIVE per-member action (individualCallings) — overrides the incomplete
    # org-aggregate in covenant_path.report._apply_profile (the Terry Stoner "no calling" fix).
    cal = fetch_callings(session, person_uuid)
    fields["calling"] = "Yes" if cal["has_calling"] else "No"
    fields["_calling_names"] = cal.get("calling_names") or []  # transient: report injects into details
    return fields
