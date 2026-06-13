# Native parity backlog (iOS + Android)

The 2026-06-13 web polish session shipped a batch of changes **web-only** (`apps/web`) by the
user's explicit call ("update WEB and keep a running list of all unupdated items for native").
This is that list. Each item needs the matching **Swift (`native/ios`) + Kotlin
(`native/android`)** edit, then a CI build (`build-native-ios.yml` / `build-native-android.yml`)
and an AVD/device pass per `native/PARITY.md`. Shared logic must stay mirrored (web
`apps/web/src/logic/` ↔ Swift `CovenantPathKit/Logic/` ↔ Kotlin `…/logic/`).

> Status legend: ⬜ not started. Update to ✅ when the native edit + CI build + device pass land.

## A. Feature batch (web commits 15fb563 … a96583f)

| # | Item | iOS | Android | Notes |
|---|---|---|---|---|
| 1 | ⬜ Birthdate rescue from the Member Tools bulk payload | native sync/adapter (if any) | same | Web fix: read `birth_date` from `/api/v5/sync` (flat/nested + roster fallback). Native only needs it if it does its own sync (it reads Supabase, so likely N/A — verify). |
| 2 | ⬜ Baptism duration drops days once ≥1 month ("3 months", not "3 months 12 days") | `Logic/Elapsed.monthsDaysAgo` | `logic/DateParse.monthsDaysAgo` | Coarse months; keep days only under a month. |
| 3 | ⬜ Sacrament attendance = last-8-weeks "Attended X of Y" (not whole-history "missed") | MemberRow + detail | same | Logic + display. |
| 4 | ⬜ Milestone eligibility: N/A excluded from missing lists; patriarchal uses the temple-recommend age gate (turning ≥12 this year) | `Logic/Milestones.swift` | `logic/Milestones.kt` | Mirror the web `milestones.ts` rules + update unit tests. |
| 5 | ⬜ Golden Hour chip tooltips (hover/long-press explain each item) + `description` on the milestone source | `Views/.../GoldenHour*` + Milestones | same | Single-source the descriptions. |
| 6 | ⬜ Golden Hour completion = full-width balanced 2-column grid, no "…" truncation | completion view | same | Equal-height rows. |
| 7 | ⬜ Principles Taught redesign — separated lesson blocks, bordered dots (empty/filled), tap/hover lesson tooltip | Principles view | same | |
| 8 | ⬜ Single editable note per member (inline edit + long-press; full note on rows; show/hide toggle persisted) reading `member_notes` (fold legacy `member_comments`) | note editor + rows | same | Backend `member_notes` (migration 0050) is live. |
| 9 | ⬜ Persist all filters/sorts/view selections + the global "remember preferences" + notes show/hide toggles (local) | per-tab state + Settings | same | |
| 10 | ⬜ Card polish — elevation, rounded corners, gentle press/hover lift via shared tokens | shared card style | same | |
| 11 | ⬜ Manual people-being-taught + suggest-and-merge (remote full override except custom notes) reading `manual_members` | add + merge UI | same | Backend `manual_members` (migration 0051) is live. |

## B. Wording / naming (web commit d4c5502 — LDS-natural labels)

Mirror these label changes; the canonical terms are the web ones. Native **test fixtures**
assert the OLD labels and must be updated in the same edit.

| New label (was) | iOS | Android |
|---|---|---|
| **Ministers assigned** (was "Has ministers") | `Logic/Milestones.swift:48` | `logic/Milestones.kt:77` |
| **Family Name Prepared** / **First Temple Visit** | `Milestones.swift:65,69` | `Milestones.kt:104,110` |
| **Missionaries & ward mission leader** | `Logic/OrgBucket.swift:36` | `logic/OrgBucket.kt:34` |
| **Action Needed** + "…still working toward each step" | `Views/Tabs/NeedsView.swift:47-48` | `ui/screens/tabs/NeedsScreen.kt:116` |
| **Still working toward: {label}** (Needs section + drill sheet) | `NeedsView.swift:109`, `GoldenHourView.swift:208` | `NeedsScreen.kt:206`, `MissingSheet.kt:39` |
| **Upcoming Baptisms** + "No baptisms scheduled yet." | `BaptismsView.swift:35,46` | `BaptismsScreen.kt:90,100` |
| **Being Taught at Sacrament** | `KPIsView.swift:45` | `KpisScreen.kt:146,150,151` |
| **Lessons with a member present** | `KPIsView.swift:164` | `KpisScreen.kt:436` |
| Table headers (Melchizedek / Ministers assigned / Ministering others / Temple recommend / Patriarchal blessing / First temple visit) | `TableView.swift:36-43` | `TableScreen.kt:354-361` |
| **No calling yet.** / **No ministering assignment yet.** | `PersonDetailView.swift:107,113` | `PersonDetailScreen.kt:209,218` |
| **Baptized** & confirmed (Rules) | `SettingsView.swift:55` | `Dialogs.kt:105` |
| Being-taught empty state reword | `GoldenHourView.swift:62` | `GoldenHourScreen.kt:98` |

**Test fixtures + spec to update with the labels:** `native/android/.../logic/MilestonesTest.kt:66`
and `native/ios/Tests/CovenantPathKitTests/LogicTests.swift:104` (both assert `"Has ministers"`);
`native/SPEC.md:85` documents the old label.

## C. Admin-only techy language for sync sentinels (web commit — ministering/field-gap session, 2026-06-13)

The backend writes internal sentinel strings (`needs-profile-api`, `blocked: insufficient calling
access`) into profile-gated columns when a field couldn't be fetched this run (the merge-upsert then
preserves last-good). These are **techy/internal** and must show **raw only to ADMINS**; regular
leaders must see friendly text instead. The web added `displayFieldValue(value, isAdmin, blank)` +
`isSentinel()` in `apps/web/src/lib/member.ts`, and routed the **Table** (`pages/tabs/TableTab.tsx`)
and **Person detail** (`pages/PersonDetailPage.tsx` — `disp(value, isAdmin)`, `StatusSections`/
`RichBody` now take `isAdmin`) through it. Admin status comes from `useDashboard().isAdmin`
(`supabase.rpc('is_admin')`).

| # | Item | iOS | Android | Notes |
|---|---|---|---|---|
| C1 | ⬜ Sentinel→friendly mapping helper (`isSentinel` + `displayFieldValue(value, isAdmin, blank)`) | new `CovenantPathKit/Logic/` helper (mirror `member.ts`) | new `…/logic/` helper | Raw to admins; "Not available yet" (detail) / "—" (table) to leaders. Sentinels: `needs-profile-api`, `blocked:` prefix. |
| C2 | ⬜ Table cells route sentinel-able columns through the helper | `Views/Tabs/TableView.swift` | `ui/screens/tabs/TableScreen.kt` | Columns: baptism_date, aaronic/melchizedek_priesthood, calling, ministering_brothers_sisters, ministering_assignment, temple_recommend, patriarchal_blessing. Also gate the filter values so filtering matches what's shown. |
| C3 | ⬜ Person-detail status rows route through the helper | `Views/Detail/DetailSections.swift` / `PersonDetailView.swift` | `ui/screens/PersonDetailScreen.kt` | Temple Recommend / Endowment / Patriarchal Blessing. (Empty value still → "—".) |
| C4 | ⬜ Resolve admin status for the audience check | needs an `isAdmin` (e.g. broker/`is_admin` RPC) threaded to the views | same | If native has no admin concept yet, default non-admin (friendly text) — leaders are the priority. |

## D. Ministering / calling / sex rescue from the bulk payload (backend — same session)

The daily sync now fills `ministering_brothers_sisters`, `ministering_assignment`, `calling`, and
`sex` from the **Member Tools `/api/v5/sync`** payload (the unit-wide EQ/RS ministering org +
`households[].members[].positions`), so they survive a dead LCR session instead of leaking the
`needs-profile-api` sentinel. This is **backend-only** (`covenant_path/membertools_adapter.py`) — the
native apps read the already-resolved values from Supabase, so **no native code change is required**;
they benefit automatically once the sync re-runs. (Listed here only so the parity log is complete.)

## Already DONE on native this session (NOT backlog — for reference)
- **OTP-lane removal** (ADR-011): native re-auth is password-only (`ReauthSheet.swift`,
  `ReauthDialog.kt`, `BrokerService`/`BrokerClient` otp methods removed, `MfaCopy` hint removed).
- **One-MFA enroll → 45-day token** capture flow on native (`/auth/web/*` routing).
- **Unlinked-sign-in empty state** ("invite or one Church login") — `DashboardView.swift`,
  `StatusScreens.kt`.
