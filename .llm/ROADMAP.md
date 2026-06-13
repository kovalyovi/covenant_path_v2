# Feedback roadmap — feedback-round3

Consolidated from two rounds of user feedback (2026-06-01). Branch: `feedback-round3`.
Legend: `[ ]` todo · `[~]` in progress · `[x]` done. Surfaces: **F**=Flutter,
**iOS**=native iOS, **A**=native Android, **be**=backend, **web**=web app.

> **Historical doc (2026-06-01).** When this roadmap was written the client was the single
> **Flutter** app (surface **F** = `apps/viewer`, including Flutter web). That app was deprecated
> 2026-06-08 and **deleted 2026-06-13** — Phase 5 below tracked rebuilding the **web** UI in
> **React (`apps/web`)**, which is now the only web surface. The **F ✓** markers on completed rows
> are an accurate record of what shipped on Flutter at the time; the maintained surfaces today are
> **React web + native iOS + native Android**. See `CLAUDE.md` and
> [`CROSS_SURFACE_UI.md`](CROSS_SURFACE_UI.md) for the current rule.

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
- [x] **N2** ✓ Done (broker `enroll.authorized` + pre-session block on Church login, all 3 apps;
  email/passkey unchanged). Block **no-access** members *at login* + sign out. **Decision (user): robust
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
- [x] **#1/#2** ✓ "Baptisms by month" KPI card — convert cohort by month over **YTD/12mo/24mo/All**
  + **best month** named + by-unit drill. Shared `baptismsByMonth` ported to all 3 surfaces. **F/iOS/A**
- [x] **#4** ✓ `docs/RULES.md` (priesthood eligibility by age/sex/tenure · calling→data-access
  matrix · convert-care ownership by tenure) + in-app **Settings → Rules & definitions** on all 3
  surfaces. **F/iOS/A + docs**
- [x] **N5** ✓ Login performance. **Finding:** dominant latency = the free-tier broker **cold
  start** (~30–60s on the first request after idle; clients already retry across ~63s). Supabase
  auth + first fetch are minor. **Fix (low-risk, no auth change):** `warmUp()` pings `/health` the
  moment the login screen opens, so the broker spins up while the user types — hiding the cold
  start. **F/iOS/A**

## Phase 3 — large backend rework
- [x] **#5/#5b** DONE: rules (+ High Council) · revocation + notify · Unicode · N7-filter · live
  audit · **per-ward sheets** (SA-created, ward-only data + recipients, reconciled) · **opt-in
  Settings toggle** (default OFF + consent copy; `set_stake_sheets_enabled` RPC) on **F/iOS/A**.
  Original scope: per-ward sheets (ward-only data); calling-based
  recipients (stake presidency/clerks/secretaries/assistants → global; ward bishopric +
  EQ/RS presidency + WML + assigned missionaries → ward sheet); **re-eval + revocation every
  run** (lost calling, lost feature access, missionary rotation); Unicode sheet names;
  preserve master styling/widths/conditional formatting; use service creds **or** the
  stake-authorized GDrive rep — else skip + notify leaders there's no sheet.
  **+ N7-sheet:** segment/omit investigators (no baptismal date) from the flat member list.
  **be/docs/small UI**

## Phase 4 — gated live ops (after user verification)
- [x] **#5-live** ✓ Audited all 3 Covenant Path sheets via Drive (incl. `1rCkwLZ6…` = the Raleigh
  NC Stake sheet): **all owner-only — nothing over-shared to strip.** The wrong sharing was in the
  *code* (now fixed: reconcile + correct recipients + notify, green-lit). Correct access applies on
  the next sync; the two stray 1 KB `covenant_path` test sheets are also owner-only.

## Phase 4b — polish (later feedback, 2026-06-01)
- [x] **N8** ✓ Content-shaped skeletons that match the real layout **and styles** — Golden Hour
  (section toggle · org filter chips · window selector · "Golden Hour completion" card of % stats ·
  per-unit grid) and KPIs/Baptisms (header · period selector · chart cards w/ window selector + two
  big stats + 170px chart + caption · Overview grid). Per-tab skeleton chosen in the loading state;
  list tabs keep the member-row skeleton. Shared `SkelCard` mirrors `SectionCard`. **F/iOS/A**
- [x] **N9** ✓ KPI charts no longer 0-pad: trim leading **and** trailing empty buckets so a short
  history shows just its data span (5 weeks → 5 points; 2 months → 2 points; no data → empty state,
  not a flat zero line). `metricData` + `baptismsByMonth`, events re-bucketed; prev overlay cut to
  the same indices. **F/iOS/A** (+ native KPI tests updated/added).

## Phase 5 — React web rebuild (after everything above)
- [x] **RT** ✓ Flutter `go_router` + `SentryNavigatorObserver` (per-route performance) — `redirect`
  auth gate replaces AuthGate; routes `/login` + `/` (dashboard shell). Verified `flutter build web`.
  **Route map R1 mirrors with React Router v7:** `/login`; `/` dashboard shell with tabs
  `/baptisms` · `/golden-hour` · `/needs` · `/kpis` · `/table`; `/person/:id`; `/settings`;
  `/invite`; `/admin`. (Flutter navigates the secondary screens via imperative push today; React
  should route them all.)
- [x] **R1** ✓ Rebuilt the **web** UI in **React** at `apps/web/` (Vite + React + TypeScript +
  React Router v7 + `@supabase/supabase-js`; charts via Recharts, lazy-loaded). Full parity: 3-mode
  login (Church+MFA / email code / passkey) with the #6 wording + N2 block + N5 warm-up; the 5 tabs
  incl. #1/#2 baptisms-by-month + #3 friends count; N7 investigator filtering; N3 sync poll; rich
  detail + notes; #4 Rules; power-user invites; admin/ops; N1 OG/SEO. All secondary screens are
  **routed** (`/person/:id` · `/settings` · `/invite` · `/admin`), code-split KPIs+Admin, a11y-first
  (semantic HTML, ARIA, focus-trapped modals, skip link, reduced-motion). Built by a background agent
  in a worktree; **cherry-picked onto `main`** (6 commits, `apps/web/` only — linear tree, no merge).
  Verified on `main`: typecheck 0 · ESLint+jsx-a11y 0 · 28/28 vitest · `npm run build` clean.
  _Intentional web gaps:_ biometric **app-lock** not ported (web-inappropriate; passwordless **passkey
  login** is); Recharts pinned to 2.x (lazy-loaded). `apps/web/.gitignore` covers node_modules/dist/.env.

## Git / workflow rule (locked)
- **Always `main`, never branch** — one repo, one commit tree, push every change to `origin/main`.
  See CLAUDE.md rule 7 + memory `git-workflow-main-only`.

## Working assumptions (correct anytime)
- **N2**: "regular member" = signed-in user with zero RLS-visible roles (no stake/ward/
  power-user grant). Trigger-bound enrollers + power users keep access.
- **N7**: "master lists" = Table + general rosters + Golden Hour + Needs. Investigators show
  only in Being-taught; their lesson counts stay where they belong.
