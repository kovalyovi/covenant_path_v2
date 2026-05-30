# Covenant Path v2 — Progress Log

Living doc tracking what's built, what works, and what doesn't. Goal: collect
covenant-path data for new members across every unit, aggregated at the stake
level — ideally via **pure API calls** (no Selenium/Playwright DOM scraping).

Stake under test: Raleigh North Carolina Stake (unit 503991), 9 wards/branches,
~112 new covenant-path members. Account is password-only (no 2FA).
Second live stake: Санкт-Петербургский (unit 615145), delegated credential.

---

## Session handoff — 2026-05-30 (PRs #15–25 merged, `main` green)

**Shipped + verified:** missionary roster client + per-ward storage (#29, migration 0026 — populated
14 missionaries/7 units for 615145; Raleigh re-sync triggered); endpoint probe → **it's NOT rate
limiting** (member-list endpoint dead/404, progress-record slow+500s) → patient 5× retries (verified
**0 failed units** after); Russia email-OTP relay (broker `/auth/email/*` + "backup sign-in", rate-
limited); Sentry; Axiom env docs; master-sheet reserved for operator's stake (#3); baptism tenure +
asc/desc sort; security hardening + tests (12 Python / 22 Dart); glass bottom nav; person-detail
"recorded yes but LCR returned no names" note. README rewritten (5 tabs + multi-stake).

**Remaining queue (start next session):**
- **M7 per-stake OAuth Drive** — design in `docs/M7_OAUTH_DRIVE.md`. **Blocked on the owner creating
  a Google Cloud OAuth client** (client id/secret + redirect). Build the no-op-until-configured
  scaffolding, then live-test. Owner is creating the GCP client later today.
- **#39 go_router** — deep-linkable tabs + back/forward (no router dep yet; needs a migration).
- **#19 per-unit refetch** — OPS button to re-pull one ward (`build_stake_report` unit filter +
  workflow `unit` input). Lower priority now that patient retries fixed the failures.
- **Axiom log views (#43–47)** — owner added `AXIOM_TOKEN` to Actions + Render (✅); build the broker
  query route + in-app log browser. Owner action remaining: **enable the Drive API** for per-stake
  sheets.
- **Node 20 → 24** — GitHub forces the actions to Node 24 on **2026-06-16**; bump checkout/setup-
  python/cache/upload-artifact majors (or confirm they run clean) before then.

**Follow-up enhancements (deeper fixes):**
- **Show minister/calling NAMES in person detail.** The names exist in the reliable sources
  (`fetch_ministering` inbound = minister names; org positions = calling name) but aren't stored —
  LCR's covenant-path *details* endpoint returns empty arrays for them. Merge those names into
  `members.details` during sync so the detail view shows real names (today it shows the recorded-yes
  note). Needs a re-sync to populate.
- **Notes sync (rickybloomfield iOS app).** That app is a private repo (don't use the owner's creds
  to read someone else's private source). It almost certainly round-trips **LCR's native member
  notes** (Member Tools → member → Notes). Plan: reverse-engineer the LCR notes read/write endpoint
  from a **HAR of viewing + adding a note**, then sync it with our existing `member_comments` table
  (migration 0017) so both apps share via LCR. Need the HAR from the owner.

---

## What's built

```
covenant_path_v2/
  tools/
    lcr_crawler.py      Phase 0 Playwright crawler (manual fallback) — cataloged 61 endpoints
    health_check.py     9 endpoint/profile-action checks -> health_report.json
    build_schema.py     full API schema inference -> lcr_schema.{json,md}
    test_suite.py       offline + --live tests -> test_report.json
    output/             catalogs, storage_state.json, action_ids.json, delegated_grants.enc (gitignored)
  lcr_client/           typed HTTP API client (requests + cookie session)
    auth.py             LcrSession — cookie session; auto-login + relogin via okta_login
    okta_login.py       ZERO-BROWSER Okta IDX login -> storage_state.json (default auth)
    client.py           LcrClient — whoami, user_context, member_list, unit_orgs, progress_*
    member_profile.py   3 profile server actions (record/recommend/ministering), self-heal
    action_config.py / action_discovery.py   build-specific action-id store + Playwright heal
    access.py           calling -> feature access matrix + runner self-check
    token_store.py      encrypted (Fernet) per-stake delegated-grant store
    delegated_login.py  leader authorizes via hosted login -> encrypted grant -> mint/verify/revoke
    access.py / leadership.py   calling->feature matrix + leadership-directory name harvest
    models.py           typed dataclasses (Member, UnitOrg, ProgressRecord, ...)
  covenant_path/
    report.py           access-aware stake aggregator -> output/covenant_path_{stake,access}.{json,csv}
    profile_cache.py    incremental cache (skip unchanged members on repeat runs) — ADR-002
  sheets_sync/          Google Sheets updater (row_mapper, service, sync) — reference-spreadsheet-sync
  backend/              Supabase: migrations/ (schema + RLS), db/sync/apply/test_rls — backend/README.md
  scripts/daily_sync.py orchestrator: login -> report+cache -> Sheets + Supabase (self or delegated)
  .github/workflows/daily-sync.yml   daily cron running scripts/daily_sync.py
  docs/DELEGATED_ACCESS.md   delegation + calling-authorization + security model
  docs/DECISIONS.md          ADR log (pros/cons/drawbacks/wins) — read this for "why"
  output/               covenant_path_stake.{json,csv}, covenant_path_access.json (gitignored)
```

Auth model: LCR uses an **Okta session cookie** (no Bearer header). Sessions are
minted **headlessly** by `lcr_client/okta_login.py` (pure requests, no browser) into
`tools/output/storage_state.json`; `LcrSession` auto-logs-in when missing and
`relogin()` re-mints on `AuthExpiredError`. The Playwright crawler is a manual fallback.

---

## Field mapping — the 13 covenant-path fields

| Field | Source | Status |
|---|---|---|
| name | `progress_record` / `progress_details` | API ✅ |
| unit | unit being queried (`user_context` child units) | API ✅ |
| birth_date | `member-list` `birth.date.display` (match by personUuid) | API ✅ |
| friends | `details.friends[]` | API ✅ |
| aaronic_priesthood | `details.priesthoodOrdinations[]` strings | API ✅ |
| melchizedek_priesthood | `details.priesthoodOrdinations[]` strings | API ✅ |
| calling | `details.callings[]` | API ✅ |
| ministering_brothers_sisters | `details.ministering.ministeringBrothers/Sisters` | API ✅ |
| living_ordinance (endowment) | `details.templeOrdinances[]` ("Not yet endowed") | API ✅ |
| baptism_date | member-profile record action (HTTP) | API ✅ |
| patriarchal_blessing | record action (`hasPatriarchalBlessing`) | API ✅ |
| temple_recommend | recommend action (`recommend.status`) | API ✅ |
| ministering_assignment (outbound) | ministering action (`ministeringBrothersAssignments[].assignments`) | API ✅ |

**All 13 fields now come from HTTP/JSON — zero Selenium in the data path.**
`python -m covenant_path.report --with-profile` produces the full stake dataset.

---

## Key API endpoints (host lcr.churchofjesuschrist.org, cookie auth)

- `GET /api/user-context?lang=eng` — current user, units, positions, roles
- `GET /api/auth/me` — identity
- `GET /api/umlu/report/member-list?unitNumber=N&lang=eng` — full member list (birth, age, email, ...)
- `GET /api/umlu/unit-org?unitNumber=N&lang=eng` — orgs/quorums/classes
- `GET /api/report/one-work/progress-record?unitNumber=N&lang=eng` — covenant path: newMemberList / returningMemberList / investigatorList
- `GET /api/report/one-work/details/{id}?legacyCmisId={cmisId}&lang=eng` — per-person detail
  - **GOTCHA:** path uses the person's `id` field, NOT `personUuid` (personUuid → 500).

Full catalog: `tools/output/lcr_api_catalog.md` (61 endpoints).

---

## What worked
- Playwright crawler with network interception → clean endpoint catalog. (~35 min plan; auto phase fast.)
- Cookie-session reuse from `storage_state.json` into a `requests.Session` — all data endpoints work.
- `progress_record` + `progress_details` give the bulk of covenant-path fields per unit.
- Looping `user_context.child_units` covers the whole stake (9 units, 112 members) in one run.
- personUuid matching against member-list for birth date is precise.

## What didn't work
- `personUuid` in the `one-work/details` path → 500. Must use `id`.
- `mltp-api/api/member/{uuid}/card` → only basic contact info (no ordinances/recommend).
- `/mlt/records/member-profile/{uuid}` fetched via `requests` with stale cookies → returns the
  page shell only (translations/menus), NO member data. Likely an auth/render issue (see open problem).
- Headless Playwright with an *injected* old `storage_state` → bounced to login, no data.
- Headless Playwright after a *fresh login* → DID render full member data (Individual + Ordinances tabs).

## Member-profile data — SOLVED via pure HTTP (no Selenium)
`lcr_client/member_profile.py`. The /mlt profile page loads data through **Next.js
Server Actions**: HTTP `POST` to `/mlt/records/member-profile/{uuid}?lang=eng` with
headers `Next-Action: <id>`, `Next-Router-State-Tree: <urlencoded tree>`,
`Accept: text/x-component`, `Content-Type: text/plain`. Response is React-flight;
rows are `id:<json>`. Three actions give us everything:
- **record** (args `["uuid","eng"]`) → member record: `birth.dateDisplay`,
  `ordinances[]` (BAPTISM/CONFIRMATION/ENDOWMENT/SEALING_TO_PARENTS → `dateDisplay`),
  `hasPatriarchalBlessing`, `currentPriesthoodOfficeType`.
- **recommend** (args `["uuid"]`) → `{recommend:{status:ACTIVE|EXPIRED, expirationDateDisplay, isLimitedUse}, hasNewRecommendInProcess}`.
- **ministering** (args `["uuid"]`) → `{ministeringBrothersAssignments:[{companions, assignments}], ministeringBrothers}` — outbound assignment = non-empty `assignments`.
All replay with plain `requests` + cookie session. Validated vs the old DOM scrape.

## Self-healing for the build-specific action ids
The `Next-Action` ids change on LCR redeploys. Handled automatically:
- `lcr_client/action_config.py` — last-known-good ids in `tools/output/action_ids.json` (seeded by DEFAULTS).
- `lcr_client/action_discovery.py` — browser-free discovery: GET the profile page,
  pull `createServerReference("<id>")` candidates from the `/mlt/.../member-profile/[id]/page-*.js`
  chunk, probe each, detect record/recommend/ministering by response shape, persist winners.
- `member_profile.py` calls discovery **once per process** on a shape miss, then retries.
- Refresh manually any time: `python -m lcr_client.action_discovery [uuid]`.

## Observability / verification
- `lcr_client/logging_setup.py` — per-session logs in `tools/output/logs/`, failure
  dumps in `tools/output/debug/`.
- `tools/health_check.py` — exercises every endpoint + the 3 profile actions,
  self-heals on miss, writes `tools/output/health_report.json`, non-zero exit on
  critical failure. Run before a sync / on a schedule.

## Complete API schema
- `tools/build_schema.py` — samples many real responses across all data sources and
  the 3 profile actions, merges into a per-object field schema (types, optional vs
  required, nullable, example). Outputs `tools/output/lcr_schema.{json,md}`.
  Broad member sampling captures optional fields (recommend, endowment, prior unit).

---

## Zero-browser Okta login — SOLVED (2026-05-26)
`lcr_client/okta_login.py` mints the LCR session in **pure `requests`, no browser
at all**. Two-phase, deliberately decoupled from LCR's own PKCE:
- **Phase 1 (authenticate to Okta):** throwaway PKCE → `POST {issuer}/v1/interact`
  → `interaction_handle`; `POST /idp/idx/introspect` → `stateHandle` + remediations;
  then drive remediations *by their own `href`* — `identify` →
  `select-authenticator-authenticate` (pick "Password" option) → `challenge-authenticator`
  (`credentials.passcode`) → `successWithInteractionCode`. The IDX transaction sets
  the org-wide Okta session cookie.
- **Phase 2 (LCR SSO):** `GET lcr /api/auth/login?returnTo=/` with the Okta session
  present → `/authorize` issues a code with no prompt → `/api/auth/callback?code=...`
  → LCR sets its session cookies. We never redeem phase-1's interaction code; the
  Okta session cookie is the only thing we need from it.
- Output: Playwright-compatible `storage_state.json` (8 churchofjesuschrist.org
  cookies) that `LcrSession` consumes unchanged. Verified via `/api/auth/me` and a
  full **9/9 health check** on the headless session.

**Wired as default auth:** `LcrSession(auto_login=True)` (default) mints a session
headlessly when none exists; `session.relogin()` re-mints; `get_json/post_json`
auto-recover **once** on `AuthExpiredError`. The Playwright crawler is now only a
manual fallback. Run directly: `python -m lcr_client.okta_login`.

**SECURITY:** password is read from env / passed in, placed only in the IDX answer
body, and never logged or persisted. IDX error `messages` are surfaced (no secrets).

## Access-aware self-check (2026-05-26)
`lcr_client/access.py` — knows what the current calling can pull before it tries.
LCR publishes a calling→feature access matrix at `/other/access-table` (embedded in
the page `__NEXT_DATA__`, at `props.pageProps.initialProps.accessTableData.membership`:
8 sections → features → `roles:[positionTypeId]`; `rolesData` = id→calling name).
- `fetch_access_matrix(session)` parses it; `runner_positions(session)` reads the
  runner's callings from user-context; `covenant_path_access(client)` /
  `print_report(client)` (CLI `python -m lcr_client.access`) report per-feature access.
- **Feature `roles[]` use the same id-space as `positionType.id`** → intersect directly.
- Caveats baked in: leadership features are perspective-based (`ward.leadership` is
  granted to *stake* roles, `stake.leadership` to *ward* roles); the matrix is UI-menu
  visibility, **not 1:1 with API access** — `health_check.py` remains the API ground truth.
- **Auth-aware fetch (fixed):** `access.py` fetches the page via `LcrSession.get_text`,
  which auto-recovers on session expiry (detects a redirect to the id. login host —
  can't use the JSON content-type check since the page is legitimately HTML).

### Role-id → calling-name catalog (task #10)
The page's `rolesData` names ~102 of the ~203 matrix role ids; the rest are secondary
seats (2nd counselors, secretaries, specialists). `access.py` keeps a **persistent,
self-improving name cache** (`tools/output/role_names.json`): seeded from `rolesData`,
merged with any `positionType {id,name}` observed elsewhere (runner positions now;
`register_names()` is the hook for future sources). We **never fabricate names** —
unknown ids stay "role N" and are **filtered out of the "who to ask" output** (named
callings only, deduped, with a "+N other seats" count), so the guidance is clean and
actionable.

**Catalog enrichment (task #11, done):** `lcr_client/leadership.py` replays the /mlt/orgs
leadership-directory server action in **pure HTTP** (action id in action_config under
"leadership"; args `["eng"]`) and harvests every `positionType {id,name}` it returns —
naming the secondary seats rolesData omits. `covenant_path_access` auto-enriches once
(when the cache looks unenriched, <150 names), so the first run fills it; it persists
after. This took the catalog from ~102 → **174** named callings (all leadership actually
present in the stake). Remaining unnamed (~30) are district/mission/MTC/ECC roles that
never appear in this stake. The action was reverse-engineered with the one-time tool
`tools/capture_callings.py` (re-run it if the leadership action id ever goes stale).
Bonus: the leadership response also carries the **person filling each calling** — the
source for a future "who to ask, *by name*".
- Runner **Stake Assistant Clerk (53)** can reach all covenant-path data; only the
  Confidential Member Information Report (Stake Clerk/President/Bishop tier) is gated,
  and the pipeline doesn't need it.

**Wired into the report (task #8):** `covenant_path.report` now runs an access
pre-flight (announces the runner's calling + what's granted + who to ask), then
**attempt-then-annotate** graceful degradation — it always tries the pull (matrix ≠
API), marks unfetchable profile-gated fields `blocked: insufficient calling access`
(never a silent blank), and if the calling lacks Member Profiles AND fetches keep
failing it stops hammering and blocks the rest. Writes `output/covenant_path_access.json`
(runner, per-feature access, **who-to-ask**, run stats, **field coverage**, sanity
warnings). Also a **post-run sanity check** flags the classic stale-action-id symptom
(a profile field uniformly empty across everyone) so silent-but-wrong data is caught.

## Delegated access — BUILT (task #9)
"A link the leader clicks → access stored, no password to us." Implemented in
`lcr_client/delegated_login.py` + `lcr_client/token_store.py`:
- `authorize` opens a real browser to LCR's hosted Okta login (password only ever
  touches Okta), captures the resulting session (incl. the longer-lived Okta `idx`
  cookie), confirms the leader's calling via access.py, records explicit consent +
  expiry, and stores it **encrypted (Fernet), scoped per-stake**.
- `mint_session` re-mints fresh LCR cookies via `/api/auth/login` (okta_login phase-2)
  from the stored Okta session, **re-verifies the calling every run** (auto-revokes on
  change), enforces expiry + the `revoke` kill-switch, writes `storage_state.json`.
- The stored secret is the session (encrypted, redacted in all logs/listings).
  Encryption key from `CP_TOKEN_KEY` env (prod) or a dev `.token_key` file.
- Verified end-to-end by the test suite (grant → mint as the leader → re-verify →
  revoke blocks re-mint). The only un-exercised bit is the headed manual-login UX
  (needs a real second person + display); the capture must run on the leader's device.
- LCR also has a **native proxy** model (`user.loggedInUser.{canProxy,allowedProxyRights}`;
  `canProxy=False` for ILYA) — preferable where available. Full design + security model:
  `docs/DELEGATED_ACCESS.md`.

## Testing & troubleshooting
- `tools/test_suite.py` — OFFLINE (crypto round-trip + redaction + key rotation,
  report degradation logic, access/okta helpers) and `--live` (access matrix, session
  re-mint building blocks, full delegated mint→verify→revoke against temp files).
  8/8 passing; persists `tools/output/test_report.json`.
- Discrepancy artifacts under `tools/output/`: `covenant_path_access.json` (field
  coverage + sanity warnings + who-to-ask), `test_report.json`, `logs/`, `debug/`,
  `health_report.json`, and the encrypted grant audit log (`delegated_login status`).

### Gotcha found via the logging (2026-05-26)
A full `--with-profile` run dumped `recommend_miss` for ~39 members and looked broken,
but the data was **correct** (recommend 52 Active / 21 Expired / 39 No — matches
baseline). Cause: LCR's recommend server action *throws server-side* (returns an
error/`digest` flight object) for members who simply have **no recommend** (new
converts/minors); `fetch_recommend` correctly maps that to "No". The per-member debug
dump was misleading noise — now a quiet debug log. A genuinely stale recommend id
shows as uniform "No" across everyone → caught by the report sanity check.

## Church login everywhere — auth broker (2026-05-27)

Goal: let users sign in with their **Church account** (username/password, like LCR) on
**web and native**, with MFA. A browser can't call the Church's Okta directly (CORS), so a
small server does it. Built `backend/auth_broker/`:
- `okta_flow.py` — resumable, MFA-aware IDX login reusing `lcr_client/okta_login` internals.
  `start_login` → success+identity or `mfa_required`+factors; `select_factor`/`verify_mfa`;
  `verify_captured_session` for the native-WebView path. Passwords/codes never logged;
  failures `dump_debug` a redacted record.
- `session_mint.py` — Supabase Admin `generate_link` → `email_otp` the app verifies (the
  project's asymmetric JWT keys make custom minting impossible, so we go through Auth).
- `app.py` — FastAPI: `/auth/password`, `/auth/mfa/select`, `/auth/mfa/verify`,
  `/auth/session`, `/health`. CORS from `ALLOWED_ORIGINS`. Request ids in every log line.
- Deploy: root `Dockerfile` (slim, no browser) + `render.yaml` (free-tier blueprint).

Viewer (`apps/viewer/lib/login_page.dart`) now has **dual login**: "Church account" (via the
broker, with MFA factor pick/verify) and "Email code" (existing OTP, for power-user invitees
with no Church account). `broker_client.dart` wraps the endpoints; `config.dart` adds
`brokerUrl` (`--dart-define=BROKER_URL`). analyze clean, build web OK, tests 5/5.

**LIVE (2026-05-27):** broker deployed to Render (`covenant-path-broker.onrender.com`),
viewer deployed to Cloudflare Pages (`app.membercovenantpath.org` + `covenant-path-app.pages.dev`).
Verified end-to-end against production: Church login → identity → Supabase mint → app-side
`verifyOtp` → real `access_token`. `SUPABASE_SERVICE_ROLE_KEY` is set on Render.

Hardening shipped same day:
- **CORS fix** — `allow_origin_regex` for `*.membercovenantpath.org`, `*.pages.dev`, localhost
  (Starlette doesn't glob `allow_origins`, so the Pages URL was being blocked). `backend/test_broker.py`
  locks it in (11 checks: allow/deny preflight, /health, mint+MFA error paths).
- **Cold-start tolerance** — Render free sleeps after ~15 min; `broker_client.dart` retries
  network failures across ~60s and shows "Waking up the sign-in service…".
- **Keep-warm** — `.github/workflows/keep-broker-warm.yml` pings /health every 10 min
  (best-effort); `docs/DEPLOYMENT.md` documents UptimeRobot (reliable) + full deploy steps.

All suites green: test_suite 10/10, test_broker 11/11, test_rls 3/3, test_power_users 5/5,
flutter test 9/9, build web OK. MFA branch is coded but unexercised (account has no 2FA).

---

## Rich member view + admin ops console (2026-05-27)

**Rich member detail (LCR-style).** The one-work details endpoint we already fetch has ~198
fields; we kept ~13 and dropped the rest. Now `covenant_path/report.py` keeps a progress-only
subtree (`_progress_subtree`: sacrament attendance, friends w/ units, callings, priesthood
ordinations, ministering names + outbound assignments, temple/self-reliance commitments,
lessons→principles, tags — **no contact PII**) into a new `members.details` JSONB
(migration 0009). `apps/viewer/lib/person_detail_page.dart` rewritten into the sectioned
two-column LCR layout (sacrament dots, friends, principles-taught circles, toggles), driven by
that JSON with a graceful fallback to the flat fields. Live sync verified: 51/51 members have
`details` populated. See [[feedback-ui-style]].

**Admin / ops console.** `app_admins` model (migration 0008): `is_admin()` (SECURITY DEFINER —
else the RLS policy recurses), `invite_admin`/`revoke_admin` (admin-gated, escalation-safe).
Broker `/admin/*` (`backend/auth_broker/admin.py`): health + freshness + counts, GitHub Actions
runs + changelog, **rescrape+repopulate** (dispatch `daily-sync.yml`), re-run; verifies the
caller's Supabase token against `app_admins` via service-role REST; GitHub features need
`GITHUB_TOKEN` (graceful without). Flutter `admin_page.dart` (gated by `is_admin`) + `admin_client.dart`.
Full model: docs/DEPLOYMENT.md → "Admin / ops console". See [[project-admin-console]].

Suites after this work: test_suite 10/10, test_rls 3/3, test_power_users 5/5, **test_admins 8/8**,
**test_broker 19/19**, flutter test 11/11, analyze clean, build web OK.

**iOS tab parity (DONE).** The dashboard is now a 4-tab bottom-nav (`dashboard_page.dart`):
On Date (members grouped by baptismal date or unit), Golden Hour (recency filter week/month/year
+ group by unit/date, milestone chips), KPIs, and Table. KPIs come from LCR's `/api/dashboard/data`
(`client.dashboard_data` → `sync.kpi_subtree` → `stakes.kpis` JSONB, migration 0011, read under
the existing stakes_select RLS): new members, people being taught, monthly sacrament attendance,
temple recommends, ministering interviews — plus new-member stats computed client-side from
`members.details`. Verified live: stake KPIs populated (112 new / 27 being taught).

**Member photos (DONE).** `backend/photos.py`: checks the manage-photos record (skips
`nophoto`), fetches `/api/avatar/{cmisId}/MEDIUM`, downsizes to a ~96px JPEG (Pillow), uploads
to a PRIVATE `member-photos` Storage bucket, and stores a 1-year **signed URL** on
`members.photo_url` (migration 0012) — read under the same members RLS, so no Storage RLS is
needed. Flutter `PhotoAvatar` shows it with an initials fallback. Verified live: bucket created,
3 photos uploaded (98 members have none), signed URL serves image/jpeg 200.

## Polish + observability (2026-05-28)

- **UI polish**: `SectionCard` (clean rounded cards) + `MaxWidthBody` (content no longer stretches
  edge-to-edge); member detail is responsive 1-col/2-col within a capped width; tabs centered.
- **Password autofill** (web): login fields in an `AutofillGroup` + `finishAutofillContext()` so
  the browser offers to save/fill.
- **Cache busting**: `apps/viewer/web/_headers` (no-cache on index.html + flutter_service_worker.js)
  so a deploy is picked up on reload instead of the SW serving a stale build (force-tracked since
  `web/` is gitignored).
- **Targeted maintenance flows**: `daily-sync.yml` takes `targets` (both/supabase/sheets) + `photos`
  dispatch inputs; the broker passes them; admin console exposes Full sync / Supabase only / Sheets
  only / Refresh photos.
- **Observability**: `lcr_client/metrics.py` times every JSON request; each sync writes a
  `sync_diagnostics` row (migration 0013) with per-endpoint latency + status histogram, units
  ok/failed, and field-coverage parity. `backend/probe.py` + `.github/workflows/probe-lcr.yml`
  (every 4h) profile the flaky endpoints between syncs. Admin console **Diagnostics** panel shows
  success %, failing units, parity bars, endpoint perf. `report._retry` now uses exponential
  backoff + jitter. First probe finding: the 500s are all on `progress-record` for ~3 units, each
  after a 20–40s server-side delay (overload → 500), recovering on retry.

**Ward-leader provisioning (#21) — DONE (2026-05-28).** Source = `GET /mlt/api/orgs?unitNumber=X`
(clean JSON, pure HTTP, stable REST — no build-specific action id). Each org's `positions[]`
carries `person{uuid,name}` + `positionType{id,name,leadership}` + `positionStatus`. `roles.py`
(`_ward_positions` + the per-ward loop in `provision_roles`) keeps ACTIVE positions whose calling
grants member-data access (same access-matrix gate as stake leaders) and provisions `ward_leader`
scoped to that unit, email-enriched from member-list. Verified live: **67 ward_leader** roles
(Bishop, counselors, clerks, exec secs, ward mission leaders) across the stake (was 0), all with
emails; RLS scopes each to their unit (`test_rls` "ward_leader sees only Ward A"). Earlier dead
ends (all ruled out): the stake `/mlt/orgs` leadership action (stake-only), member-list `positions`
(null), and the RSC page payload (not cleanly parseable) — the people are nested under
`position.person` (keyed `uuid`/`name`), which a buggy walker had missed.

---

## Responsive UI overhaul + Android (2026-05-28)

Reworked the viewer to match the reference iOS app and feel like a real app on the browser:
- **No dropdowns** — On Date + Golden Hour render **cards** (a card per unit with the unit as
  title + member rows; or a flat list **sorted by date** with the unit as right-side metadata).
  Full long dates (`intl`), full names, count badges.
- **Golden Hour** drops Baptized — completion is integration milestones only (Friends, Calling,
  Ministering ×2, Aaronic, Melchizedek). Week/Month/Year/All recency filter.
- **KPIs** = iOS-style **line-chart cards** (`fl_chart`): "New Members at Sacrament" weekly trend
  computed from `members.details.sacrament`, plus stake sacrament/recommend/ministering and an
  overview stat card, each with delta badges.
- **Table** mimics the master spreadsheet — color-coded cells (Yes=green / No=red / N/A=grey;
  recommend Active=green·Expired=amber) + styled header row.
- **Responsive, 3 breakpoints** (`tierFor`): phone = bottom nav + 1 col; tablet/desktop = side
  `NavigationRail` + 2/3-column cards, width-capped & centered. Detail page = iOS-style header card.
- **Login** offers browser password autofill (`AutofillGroup` + `finishAutofillContext`).
- `web/_headers` (force-tracked) sets no-cache on index/SW so deploys aren't served stale.

**Android app:** `flutter build apk --release` (prod dart-defines) → installable APK at
`apps/viewer/build/app/outputs/flutter-apk/app-release.apk`. Pinned the generated `android/`
toolchain to AGP 8.7.3 / Kotlin 2.1.0 / Gradle 8.11.1 (the `flutter create` default AGP 9.0.1 +
Gradle 9.1 broke plugins with a `DefaultAndroidSourceSet` cast error). `android/` is gitignored;
re-pin after any `flutter create`.

Suites after this work: flutter analyze clean, flutter test 15/15, backend rls/power_users/admins
+ broker + offline all green.

---

## Open problems / next steps
1. Confirm the profile actions work with a *fresh crawler* `storage_state` (one that
   never visited /mlt) — may need a one-time /mlt session warm-up. (Not seen yet with
   the okta_login-minted session; health check's profile_* all pass.)
2. Daily sync: with zero-browser login, **GitHub Actions** is now unblocked (needs
   `LCR_LOGIN`/`LCR_PASSWORD` secrets). Then Supabase backend + typed models from the
   schema, and Google Sheets export.

### Auth caveat (legacy, Playwright path only)
`attempt_login` often logs "selectors not found / timed out" yet the headless
Playwright session still ends up authenticated. Now moot for normal runs since
`okta_login` is the default; relevant only if falling back to the crawler.
