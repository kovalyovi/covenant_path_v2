# Testing — lanes, rules, and the scenario catalog

This is the **source of truth for what must be tested and when** (companion to CLAUDE.md rule 4).
The 2026-06-10 enroll outage (a `NameError` that broke **every** consented enroll for 8 hours and
shipped because no test drove the eval past the fast paths) is the reason this file exists: every
user-visible behavior gets a scenario here, every scenario gets a test, and CI runs the right
suites whenever their code is touched.

## The rule

1. **Touch a feature → run its lane locally → CI re-runs it on push** (`.github/workflows/tests.yml`
   path-filters do the mapping; nightly runs everything including the live lanes).
2. **A user-facing change MUST add or extend a scenario row below** (and its test) in the same
   commit. A bug fix MUST add the regression scenario that would have caught it.
3. **Public repo invariants**: committed fixtures are 100% fictional (unit 999001+, fake names);
   no secrets in workflows readable from forks (no `pull_request` triggers on secret-bearing
   jobs); `CP_TEST_MODE` is never set on Render/CI-sync — `tools/test_suite.py::
   test_hosts_test_mode_guard` proves the host override is dead without it.

## Lanes

| Lane | What it is | Command | Secrets | CI trigger |
|---|---|---|---|---|
| Backend offline | Pure-logic + crypto + broker unit/regression suites | `python tools/test_suite.py` · `python -m backend.test_broker` | none | push (backend paths) + nightly |
| Lint | `ruff` F821 (undefined names — the enroll-outage class) | `python -m ruff check --select F821 backend lcr_client covenant_path sheets_sync scripts tests` | none | push (backend) + nightly |
| **Backend e2e (mock lane)** | The **real broker + real lcr_client** against the fixture **mock LCR/Okta** (`tests/mock_lcr`) + **Supabase stub** (`tests/supabase_stub`), via the `CP_TEST_MODE=1` host override | `python -m pytest tests/e2e -q` | none | push (backend) + nightly |
| Web unit | vitest + typecheck + build | `npm run typecheck && npm run test && npm run build` (apps/web) | none | push (web) + nightly |
| **Web e2e (UI lane)** | Playwright against the real app with broker/Supabase mocked at the network edge | `npm run e2e` (apps/web) | none | push (web) + nightly |
| Live smoke (prod) | The existing live suites against production Supabase | `python -m backend.test_rls` · `test_power_users` · `test_admins` · `test_login_audit` · `test_reconcile` · `test_calling_overrides` | prod secrets | nightly + dispatch only |
| **RLS matrix (test project)** | Migrations + seeded personas + the role×table visibility matrix against the **dedicated test Supabase project** | `python -m tests.seed && python -m pytest tests/test_rls_matrix.py` | `CP_TEST_SUPABASE_*` | nightly + dispatch (skips until the project exists) |
| **Fullstack e2e (LIVE)** | Playwright `fullstack` project: real browser → real broker → mock LCR → the TEST project (RLS live). The config boots the whole stack itself (`tests/fullstack_stack.py` + vite) | `E2E_FULLSTACK=1 npx playwright test --project=fullstack` (apps/web; needs `.env` CP_TEST_* + seeded project) | `CP_TEST_SUPABASE_*` | local / dispatch |
| Native | iOS/Android build + manual AVD pass | CI `build-native-*.yml`; AVD per `native/PARITY.md` | none | push (native paths) |

## Test environment

- **Mock hosts**: `lcr_client/hosts.py` — `CP_TEST_MODE=1` + `CP_TEST_LCR_BASE`/`CP_TEST_IDENTITY_BASE`
  point ALL Church-host traffic at `tests/mock_lcr`. Without `CP_TEST_MODE` the overrides are
  ignored (guard test). Never set `CP_TEST_MODE` outside tests.
- **Mock personas** (username / password → behavior): `president.complete`/`pw-president`
  (no-MFA stake president, full access), `wardleader.partial`/`pw-ward` (partial coverage),
  `member.nocalling`/`pw-member` (valid login, no calling — the gate case), `member.mfa`/`pw-mfa`
  (MFA shape A, code `123456`), `member.mfab`/`pw-mfab` (shape B), `member.mfaw`/`pw-mfaw`
  (shape A + a webauthn security key on the menu; wrong code answers the PROD field-level 401 —
  the 2026-06-11 incident), `user.locked` (locked account),
  anything else → "Authentication failed". Failure injection: `POST /__test/control`
  (`lcr_5xx` / `identity_timeout` / `sso_reject` / `healthy`).
- **Dedicated TEST Supabase project** (Phase B, owner action): create a SECOND free Supabase
  project; set `CP_TEST_SUPABASE_URL` / `CP_TEST_SUPABASE_ANON_KEY` /
  `CP_TEST_SUPABASE_SERVICE_ROLE_KEY` / `CP_TEST_SUPABASE_DB_URL` in `.env` (local) and GitHub
  secrets (CI). `tests/seed.py` refuses to run when these are unset **or equal the prod values**.
- **HAR-derived schemas**: `tools/output/har_schema_report.md` + `har_schemas.json` (gitignored,
  regenerable) document the REAL LCR response shapes the mock fixtures mirror — including real
  failure bodies (`auth/me` 502 `text/plain`, `one-work/*` 500 empty body, Okta `sessions/me`
  404-before-login) and the no-calling persona. Never copy real values into fixtures.

## Scenario catalog

Status: ✅ covered (lane · test) · 🔶 Phase B (needs test project / fullstack lane) · ⬜ TODO.
**Add rows here as features land — a PR that changes behavior without touching this table is
incomplete.**

### A. Login & messages

| # | Scenario | Status |
|---|---|---|
| A1 | Happy password login (no MFA) → session minted, authorized, audit row | ✅ e2e-mock · `tests/e2e` |
| A2 | Wrong username/password → friendly "username or password is incorrect", 401; audit keeps RAW cause + `okta:bad_credentials` | ✅ offline `test_broker` + e2e-mock + Playwright `login-messages` |
| A3 | Locked account → unlock instructions message | ✅ offline `test_broker::test_friendly_okta_errors` |
| A4 | LCR outage after password OK (502) → honest "LCR itself appears to be down" 503; audit `identity:lcr_5xx` + root cause | ✅ offline (classifier) + e2e-mock (`lcr_5xx` scenario) |
| A5 | LCR slow/timeout → "slow or briefly down" message; retries within budget | ✅ offline `test_broker` (retry tests, 6802d6e) |
| A6 | SSO rejected → "try signing in at lcr.churchofjesuschrist.org" | ✅ offline (classifier) |
| A7 | Outage suffix "failing for everyone since HH:MM" after 2+ distinct users; `/health` `lcr: degraded` | ✅ offline `test_broker` |
| A8 | No-calling member blocked IN the response (first login sync gate; cached fast block on repeat) | ✅ offline `test_broker` + e2e-mock |
| A9 | No-calling block message = `kNoAccessMessage`, stays on login, no session | ✅ Playwright `login-messages` |
| A10 | MFA shape A: factor list → select → code → success; wrong code → friendly retry, state preserved | ✅ e2e-mock + Playwright `login-mfa` |
| A11 | MFA shape B (auto-sent single factor) | ✅ e2e-mock |
| A18 | **2026-06-11 MFA hardening** — unsupported factors (webauthn/push) FILTERED from the menu; all-unsupported → actionable "add a method at churchofjesuschrist.org"; answer body uses the challenge's declared field (`totp` vs `passcode`); field-level "Invalid code" 401 (no top-level messages) → friendly retry, NEVER raw IDX JSON; pending state refreshed from the failure payload (retry-safe); code normalized (spaces/hyphens) | ✅ offline `test_broker` (regression suite, fails pre-fix) + e2e-mock `test_mfa_webauthn_filtered_and_field_level_invalid_code` |
| A19 | MFA audit completeness: `mfa_pending` row on hand-off (offered + dropped factor types), `mfa_select_failed` audited, `mfa_failed` carries username + factor type in phase (`okta:mfa_bad_code:phone_number`) | ✅ offline `test_broker::test_mfa_pending_and_select_failures_audited` + e2e-mock |
| A20 | MFA UI hygiene (all 3 surfaces): code input clears on factor switch + failed verify; digits-only, Verify gated on ≥6; "Send a new code" with 30s cooldown; "Start over" escape; mode switch + passkey button hidden mid-MFA | ✅ Playwright `login-mfa` + `reauth-dialog` (web) · 🔶 native via CI builds + AVD spot-check (PARITY.md 2026-06-11) |
| A12 | Cached-identity fast lane: repeat login ~zero LCR (`timing.lane == "cached"`) | ✅ e2e-mock (hit counters) |
| A13 | Broker cold start → "Waking up…" status, login still completes | ✅ Playwright `login-messages` + existing `broker.test.ts` |
| A14 | Email-OTP login (direct + relay; cooldown) | ✅ offline (`test_email_relay_validation`) · 🔶 fullstack browser pass |
| A15 | Passkey register + passwordless login ceremony (CDP virtual authenticator; attestation row in the real `webauthn_credentials`; RLS session minted) | ✅ fullstack `apps/web/e2e/fullstack/passkey.spec.ts` (caught the `_rest` duplicate-headers 500 that broke BOTH prod ceremonies, fixed 2026-06-11) |
| A16 | Email/auth_id RLS spoof probe: two auth users sharing an email see only their own scope | 🔶 `tests/test_rls_matrix.py` |
| A17 | Unauthorized stranger from a NEW stake (valid Church account): LCR up → calling gate or empty-scope; LCR down → outage message (never data) | ✅ e2e-mock (A4+A8) · 🔶 matrix (zero-row visibility) |

### B. Enrollment & credential lifecycle

| # | Scenario | Status |
|---|---|---|
| B1 | Consented enroll stores credential (eval → scrape → RPC) — **the 2026-06-10 NameError regression** | ✅ offline `test_broker::test_full_eval_enroll_reaches_scrape_and_stores` + e2e-mock |
| B2 | Re-enroll after REVOKE → row un-revoked, failure state cleared | ✅ e2e-mock (seeded revoked row) + offline RPC-semantics stub + **fullstack browser loop** (`apps/web/e2e/fullstack`) |
| B3 | can_enroll offer for a credential-less stake (post-login offer, consent moved off login form) | ✅ offline + e2e-mock + Playwright `login-enroll-offer` |
| B4 | can_improve takeover offer (higher access replaces incomplete credential; lower never clobbers healthy higher) | ✅ offline (`onboarding.should_take_over`) · 🔶 e2e-mock persona pair |
| B5 | Consented enroll that stored NOTHING says so (dialog stays open with server error; no fake success toast) | ✅ Playwright `reauth-dialog` (web logic shipped eb7107f) |
| B6 | Slow access scrape → login answers within budget with enroll `{"deferred": true}`; the background eval still completes (audit lands) | ✅ `tests/e2e/test_deferred_report_offboard.py` (short-budget broker + `slow_access` scenario) |
| B7 | Stale credential (sync failed) → provider banner "Re-authorize"; non-provider "take it over" variant | ✅ Playwright `banners-empty-states` |
| B8 | Credential longevity: no refresh token ⇒ cookie-lifetime-bound. PRE-EMPTIVE aging nudge after a healthy sync (`CP_CREDENTIAL_AGE_ALERT_DAYS`, default 21, 0 disables; once per credential generation — re-enroll re-arms via `age_notified_at < updated_at`, migration 0047); stale alert fires once per failure streak | ✅ feature (`_maybe_age_alert`) + `tests/test_credential_and_email_gates.py` (B8 section) + F2 concurrency |
| B9 | Revoke: provider-only, idempotent ("already_revoked"), admin override path | ✅ live smoke + e2e-mock |
| B10 | Enrollment-status state machine none/active/stale/revoked incl. `is_provider`, no-role fallbacks | ✅ e2e-mock |
| B11 | Provider binding on enroll (0029 trigger): enroller immediately sees their whole stake | 🔶 matrix (seeded enroll → visibility) |
| B12 | Calling change: released leader loses access by next sync/login (cache heals via background refresh); newly-called heals the other way | ✅ offline (cache-refresh tests) · 🔶 matrix (provision_roles re-run flips visibility) |

### C. Sync settings, schedule, Drive

| # | Scenario | Status |
|---|---|---|
| C1 | Sheet actions follow credential state (revoked→Re-authorize only; stale→Re-authorize+Revoke; active provider→Sync now+Revoke; none→Set up) — **the "Revoked but offers Revoke" report** | ✅ web vitest `sync_settings.test.tsx` + Playwright `sync-settings` (parity: iOS/Android edits flagged for CI/AVD) |
| C2 | `/auth/sync-now` 409 on revoked credential (server gate behind the hidden button) | ✅ offline `test_broker` + e2e-mock |
| C3 | Sync-now: provider-only 403; partial-coverage warning surfaced | ✅ offline · ✅ e2e-mock |
| C4 | Schedule: ET-hour set / pause / resume; off-hour cron no-op; mid-day change takes effect same day | ✅ partial (broker get/set) · ⬜ TODO prepare-step gating unit test |
| C5 | Wipe data ≠ revoke (members deleted; credential + roles stay; repopulates) | ✅ offline `test_provider_wipe_data` |
| C6 | Drive connect/disconnect/needs-reconnect states; per-stake sheet | ✅ Playwright `sync-settings` (status rendering) · 🔶 fullstack OAuth loop |
| C7 | Sheet sharing = computed recipients EXACTLY (policy callings + missionaries; ward clerks/teachers never auto-shared; stake sees all wards; released leaders drop out); `reconcile_viewers` notifies ONLY newly-added viewers and never removes the owner/SA | ✅ `tests/test_sheet_sharing.py` (offline, mocked Drive) + read-only live audit `python tools/verify_sheet_sharing.py` (lists permissions only — zero shares/notifications) |
| C8 | The REVOKER sees the revoked state immediately (banner + settings refresh, no page reload) | ✅ fullstack lane (caught the missing `reloadEnrollStatus` after revoke, fixed 2026-06-11) |

### D. Data visibility (RLS) & person views

| # | Scenario | Status |
|---|---|---|
| D1 | Stake leader sees all units; ward leader only theirs; no-role sees zero; anon sees zero | ✅ live smoke `test_rls` + seeded matrix `tests/test_rls_matrix.py` (7/7 vs the test project, 2026-06-11) |
| D2 | Power user: exact scope clone (stake- and ward-level), recursive, escalation-safe, revoke removes | ✅ live smoke `test_power_users` + seeded matrix (clone scope) |
| D3 | Multi-stake email collision: same email roles in 2 stakes → union scope, no bleed | 🔶 matrix |
| D4 | Notes (member_comments) scoped by RLS; visible to same-scope leaders | ✅ Playwright `person-views` (render+post) · 🔶 matrix (cross-scope denial) |
| D5 | Member object variants render everywhere: full / all-null / empty-lists / investigator+goal-date / mid-milestones (no crashes, correct chips) | ✅ Playwright `person-views` fixtures |
| D6 | Admin-only tables (login_audit, access_audit) invisible to non-admins | ✅ live smoke `test_login_audit`/`test_admins` |
| D7 | /report scoped to the caller's roles (stake-wide = all units; ward leader = their unit only, no leakage; no-role = empty "none" scope) | ✅ `tests/e2e/test_deferred_report_offboard.py` |

### E. Sync & data integrity (backend jobs)

| # | Scenario | Status |
|---|---|---|
| E1 | Reconcile (hard-delete departed) defers during degraded runs (>3 candidates + failed unit) | ✅ live smoke `test_reconcile` |
| E2 | Field-meta staleness: profile-denied runs preserve good data, mark stale | ✅ `test_field_meta` |
| E3 | Per-stake scoped dispatch (enroll kickoff + sync-now never fan out) | ✅ offline (dispatch allowlist) + code-asserted inputs |
| E4 | Daily-sync delay-robust gating (due-by-hour, late-cron fires, paused, failed-run-stays-due) | ✅ `tests/test_sync_gating.py` (offline) |
| E5 | `_revoke_if_ineligible` re-verifies callings each sync (revokes ONLY on a positive no-access read; inconclusive/error never revokes; stewardship safety net) | ✅ `tests/test_sync_gating.py` (offline) |

### F. Emails (non-spammy invariants)

| # | Scenario | Status |
|---|---|---|
| F1 | Enroll confirmation: once per enroll, best-effort | ✅ e2e-mock (notify stubbed; assert single call) |
| F2 | Stale-credential alert exactly once per failure streak (atomic claim under CONCURRENT syncs; success re-arms the edge) | ✅ `tests/test_credential_and_email_gates.py` (test-project DB) |
| F3 | Invitations: emailed-once, revoked skipped, daily cap, failed send stays pending for retry | ✅ `tests/test_credential_and_email_gates.py` (test-project DB) |
| F4 | Digest once per leader per run + never for an empty scope; handoff fires once per (person, phase), unsent transitions not burned; weekly respects the owner-preview gate | ✅ `tests/test_digest_and_handoff_gates.py` (test-project DB) |
| F5 | Admin-invite approval: token-gated, single email, expiry | ⬜ TODO |

### G. Onboarding / offboarding a stake

| # | Scenario | Status |
|---|---|---|
| G1 | New-stake first enroll: stake row created, kickoff scoped, "setting up your stake" state, roles provisioned by first sync | ✅ e2e-mock (enroll+kickoff stubs) · 🔶 matrix (post-sync visibility) |
| G2 | Offboard tiers: wipe (members gone + freshness reset; roles + credential survive) → remove (credential/members/roles/diagnostics/stake erased, admin-gated 403 for others, idempotent) | ✅ `tests/e2e/test_deferred_report_offboard.py` + offline wipe test |
| G3 | Power users of an offboarded stake see empty app, never errors | 🔶 matrix |

## When something breaks in prod

Write the post-mortem scenario into this catalog **first**, then the regression test, then the
fix (the test must FAIL against the broken code — see `apps/web/src/test/modal.test.tsx` and
`test_broker.py::test_full_eval_enroll_reaches_scrape_and_stores` for the pattern).
