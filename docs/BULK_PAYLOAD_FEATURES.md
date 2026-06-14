# Bulk `/api/v5/sync` payload — feature feasibility probe (2026-06-14)

Read-only, PII-safe probe of the Member Tools bulk payload (stake 503991, the operator's own stake;
token refreshed from the stored 45-day `membertools_refresh_enc`, no live LCR session needed). Raw dump
saved locally to the gitignored `tools/output/api_profile/raw/probe_sync.json`. This settles what the
12-item overhaul's new data features (#1e attendance, #3a missionaries, #11 photos, #12 staffing) can
draw from the **session-independent** bulk payload vs. what stays **re-auth-only** (live LCR session).

## Summary

| Feature | Source | Session-independent? | Verdict |
|---|---|---|---|
| **A1 — Sacrament attendance (8 wk)** | `covenantPathMembers[].sacramentAttendance` = `[{date, attended:bool}]` (26 weeks; **74/76 members populated**) | ✅ yes | **SHIP.** Already parsed into `details.sacrament`; web `kpis.sacramentWindow` already computes an 8-week `{attended,total}`. Native Kpis has NO sacrament logic yet → new 3-surface work for the bucket helper + UI. |
| **A4 — Staffing / leadership** | `households[].members[].positions` = `[{uuid,type,name,unitNumber,activeDate,setApart}]` (271 distinct callings incl. Bishop, Branch President, Asst Ward Mission Leader, EQ/RS presidency…) | ✅ yes | **SHIP, built with Phase 10.** The leaders are NOT covenant-path `members` rows, so this needs its OWN per-unit store with RLS mirroring `members`/`units` (stake leader → all units; ward leader → own unit). Build the table + RLS + extraction + RLS-matrix test together with the Leadership-tab consumer so the test exercises the real query path. |
| **A3 — Missionaries assigned** | `missionariesAssigned` = groups of `{mission:{name,phone,email,address,unitNumber,unitType}, missionaries:[{uuid,names,sex,email,type}]}` (10 groups, 24 missionaries); also `missionariesServing[29]` (members serving elsewhere), `missionLeaders[1]` (mission pres couple) | ✅ yes (bulk) | **SHIP name/email/type per group.** ⚠ The per-missionary record has **no phone, no companionship, no photo**; the GROUP carries a phone/email and a `unitNumber` whose ward-vs-mission semantics are **unconfirmed** vs. the known-correct `/mlt/orgs/missionary` path. Keep the existing `/mlt` fetch (correct per-ward + phone) as the authoritative source at re-auth; the bulk payload is the session-independent fallback. **Companionship grouping + missionary photos are NOT in any source → documented gap.** |
| **A2 — Member photos** | NOT in the payload — only `households[].*.privacy.photo` = a VISIBILITY setting (`LEADERS`/`STAKE`/`WARD`). No `cmisId`, no avatar/photo URL. `/api/v5/sync/files` rejects standard calls (POST 406 / GET 405). | ❌ no | **Re-auth-only, deferred.** Photos need the LCR `GET /api/avatar/{cmisId}` (live session) and `cmisId` only comes from the `/mlt` per-member profile fetch (`report.py` one-work path). `backend/photos.py` already does the fetch→private-bucket→signed-URL; wiring it into `enroll._refresh_profile_worker` (warm session, capture `cmisId`, fetch avatar) + a daily re-sign-only pass is the path — low value (re-auth-only, like patriarchal), built later. `/api/v5/sync/files` is a future investigation for MT-token photos (needs protocol reverse-engineering). |

## Notes / gotchas
- `covenantPathMembers` = 76, `covenantPathInvestigators` = 17 (the covenant-path roster — NOT the whole
  stake; the 1672 `households` are the full directory, where leadership callings live).
- `sacramentAttendance` is also present top-level (`array[112]` — unit-wide weekly counts) and per member.
- Per-member `positions` only exists on members who hold a calling (absent otherwise) — iterate tolerantly.
- The household member record carries `mrn` + `uuid` but no `cmisId`; the LCR avatar endpoint keys on
  `cmisId`, so member `uuid`/`mrn` are not directly usable for `/api/avatar/`.

## Reproduce
Refresh the operator stake's stored token and `membertools.fetch_sync(access)`, then inspect (see the
session transcript for the exact PII-safe probe). Raw stays in `tools/output/api_profile/` (gitignored).
