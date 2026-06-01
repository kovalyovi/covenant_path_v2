# Feedback roadmap — feedback-round3

Consolidated from two rounds of user feedback (2026-06-01). Branch: `feedback-round3`.
Legend: `[ ]` todo · `[~]` in progress · `[x]` done. Surfaces: **F**=Flutter,
**iOS**=native iOS, **A**=native Android, **be**=backend, **web**=Flutter web.

> **Every UI item below must land in F + iOS + A** (see [`CROSS_SURFACE_UI.md`](CROSS_SURFACE_UI.md)).

## Decisions locked with the user
- Native: edit **all** surfaces incl. `native/android` this pass.
- Live Google Drive ops: **code first → user verifies computed recipient lists → then** the
  destructive removal/recreate + share notifications.
- "Baptised **and** confirmed" = the convert/new-member cohort counted **by baptism month**
  (no separate confirmation-date scraping — confirmation follows baptism within days).
- Order: **quick wins first**.

## Phase 0 — foundation
- [x] Branch `feedback-round3`; `.llm/` cross-surface docs + this roadmap.

## Phase 1 — quick wins
- [x] **#6** Login/privacy wording → match real *most-elevated-wins-if-incomplete* enrollment
  logic (`backend/onboarding.py`, `0020_enroll_rpc.sql`). The current copy overstates that
  any login's Church credentials gather data. **F/iOS/A + docs**
- [x] **#3** Surface friends **count** — captured as `friends_count` (migration 0031), synced,
  already captured in `report.py`; just needs the column in the select + display. **F/iOS/A**
- [ ] **N2** Block **no-access** members *at login* + sign out. **Decision (user): robust
  approach** — the broker can't tell a regular member from a not-yet-set-up leader post-login
  (both = no-role + no-credential), so surface the user's covenant-path access (calling's
  granted features) at **Church login**; block when no data-granting calling AND no role/
  power-user grant (email/passkey no-role also blocked). _Re-tiered to needs broker + all 3
  apps — done AFTER the smaller quick wins._ **be/F/iOS/A**
- [x] **N3** Auto-poll sync status every ~5s while the "syncing…" banner is active;
  auto-clear/refresh when done. **F/iOS/A** ✓ — poll added to `_DashboardPageState`,
  `DashboardViewModel`, `DashboardStore`; bounded by the existing 30-min crashed-run guard.
- [x] **N7** _Already implemented on all 3 surfaces (verified)_ — Table / Needs / Golden-Hour
  "New Members" filter `kind == 'investigator'` out; investigators appear only in **Baptisms**
  (planned dates), Golden Hour **"Being Taught"**, and KPI counts. No search/all-members list
  exists. **NOTE:** the Google **Sheet** still lists investigators flat — fold into #5.
  **F/iOS/A** ✓ — _User confirmed the sighting was the Google **Sheet** → handled in #5._
- [x] **N6** Android bottom-tab overlays card bottom borders → 12dp bottom padding on the
  content Box in `DashboardScaffold` (Android-only; Flutter/iOS handle their own nav clearance). **A** ✓
- [x] **N1** OG / Twitter Card + canonical + theme-color in `web/index.html` (uses the rebranded
  `Icon-512.png` as the OG image; absolute URLs at `app.membercovenantpath.org`). **web** ✓
- [x] **N4** Banners → `.ultraThinMaterial` frosted glass (they overlay scrolling content, so the
  material frosts). System chrome (`TabView`/nav) is already translucent; cards keep the native
  grouped-background convention (material there has nothing to frost). **iOS** ✓

## Phase 2 — medium
- [ ] **#1/#2** Baptized-convert cohort by **unit × month** over YTD/12/24/all + **best
  month** (named). **F/iOS/A**
- [ ] **#4** `docs/RULES.md` (priesthood eligibility by age/sex/tenure · calling→data-access
  matrix · convert-care ownership by tenure) **+ in-app Rules page / ⓘ icons**. **F/iOS/A + docs**
- [ ] **N5** Login performance + robustness — investigate broker cold-start / Supabase auth /
  first-fetch; report before risky changes, then improve. **F/iOS/A/be**

## Phase 3 — large backend rework
- [ ] **#5** Spreadsheet access overhaul: per-ward sheets (ward-only data); calling-based
  recipients (stake presidency/clerks/secretaries/assistants → global; ward bishopric +
  EQ/RS presidency + WML + assigned missionaries → ward sheet); **re-eval + revocation every
  run** (lost calling, lost feature access, missionary rotation); Unicode sheet names;
  preserve master styling/widths/conditional formatting; use service creds **or** the
  stake-authorized GDrive rep — else skip + notify leaders there's no sheet.
  **+ N7-sheet:** segment/omit investigators (no baptismal date) from the flat member list.
  **be/docs/small UI**

## Phase 4 — gated live ops (after user verification)
- [ ] **#5-live** Present computed per-sheet recipient lists → on user OK: strip non-owner
  viewers / delete + recreate `1rCkwLZ6HV8qRFJJFfxgWDiUWWc0ZeoyRPcvQOYPl4EE`, apply correct
  access, enable share notifications. **Irreversible — never run unprompted.**

## Working assumptions (correct anytime)
- **N2**: "regular member" = signed-in user with zero RLS-visible roles (no stake/ward/
  power-user grant). Trigger-bound enrollers + power users keep access.
- **N7**: "master lists" = Table + general rosters + Golden Hour + Needs. Investigators show
  only in Being-taught; their lesson counts stay where they belong.
