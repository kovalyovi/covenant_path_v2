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
| **A3 — Missionaries assigned + COMPANIONSHIPS** | `missionariesAssigned` is an array of **companionships** — each `{unitNumbers:[Int]?, phone, email, areaId, mission, missionaries:[{uuid,names,sex,email,type}]}` (10 companionships, 24 missionaries; `unitNumbers` = the wards a companionship serves; phone/email are companionship-level/shared; null `unitNumbers` = mission-wide/senior). Plus `missionariesServing[29]`, `missionLeaders[1]`. | ✅ yes (bulk) | **CORRECTED (was wrong before): companionship grouping IS available.** Each `missionariesAssigned` entry IS a companionship (members + shared phone/email + the `unitNumbers` it serves). Confirmed against Ricky Bloomfield's Mission-KPIs (`MemberToolsSync.companionshipsByUnit()` expands each companionship across its units). **SHIP: per-unit companionships with names/email/type + shared phone, grouped by companionship.** |
| **A2 — Member + missionary PHOTOS** | **`POST /api/v5/sync/files`** with `Accept: application/zip, application/octet-stream, */*` (NOT json — that 406s) returns a **ZIP of WebP photos keyed by UUID**. Body = the normal sync body + `"exclusions":[{"features":[...]}]` to pick photo sets: `MEMBERS_PHOTOS`, `HOUSEHOLDS_PHOTOS`, `MISSIONARIES_*_PHOTOS`, `TEMPLES_PHOTOS`. ZIP layout: `MEMBERS_PHOTOS/<uuid>.webp`, `MISSIONARIES_ASSIGNED_PHOTOS/<uuid>.webp`, `MISSIONARIES_SERVING_PHOTOS/<unit>/<uuid>.webp`, + root `sync.json`. | ✅ yes (MT token!) | **CORRECTED (was wrong before): photos ARE available, session-independent, via the Member Tools token — solves #11 AND missionary photos.** My earlier probe 406'd only because I sent `Accept: application/json`. Source: Ricky's `MemberToolsClient.fetchMissionaryPhotosArchive` + `MissionaryPhotoBundle` (he EXCLUDES member/household/temple to get only missionaries; omit `MEMBERS_PHOTOS` from exclusions → member photos too). **Plan: a daily `/api/v5/sync/files` fetch → unzip → downsize → private Supabase bucket → signed URL on `members.photo_url` / the missionary record. No LCR session, no cmisId, no re-auth.** Supersedes the LCR-avatar `backend/photos.py` approach. |

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
