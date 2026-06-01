# Covenant Path Platform — Rules & Architecture (read first)

This file is the source of truth for **how to make changes consistently** across the
backend and all client views (web / iOS / macOS / Android). Read it before editing.
Companion docs: `PROGRESS.md` (status), `docs/DECISIONS.md` (ADR log — the *why*),
`docs/DELEGATED_ACCESS.md`, `docs/CUSTOM_API_KEYS.md`, `docs/DEPLOYMENT.md` (broker +
viewer hosting), `backend/auth_broker/README.md`, `apps/viewer/ARCHITECTURE.md`.

## The shape of the system

```
LCR (church data)
  └─ backend (Python) ── daily GitHub Action ──> Supabase (Postgres + RLS)
       lcr_client/      okta_login, client, member_profile, access, leadership
       covenant_path/   report (the 13 fields) + profile_cache
       sheets_sync/     Google Sheet mirror
       backend/         migrations, db, sync, roles, credentials, mailer
                                   │  reads (RLS-scoped by login)
  Flutter app (apps/viewer) ──────┘   ONE codebase → web + iOS + macOS + Android
```

- **Clients never touch LCR.** They read **Supabase**, scoped by the signed-in user.
  LCR scraping lives only in the backend. (Why: browser CORS + central aggregation — ADR-005.)
- **Access control is RLS, keyed by the login email OR a bound LCR identity.** Roles are
  auto-provisioned from LCR callings; power users are cloned scopes (ADR-001, 0002/0004/0005).

## Golden rules

1. **Never commit secrets.** `.env`, `service_account.json`, `*.enc`, `.token_key`,
   `storage_state.json`, `tools/output/`, `output/` are gitignored. Before any commit,
   the workflow is: `git add` → check `git status` has no secret → commit. Pass secrets to
   subprocesses via stdin/env, never echo them.
2. **One source of truth per concept.** The covenant-path fields, the Golden-Hour
   milestones, the sheet columns, and the RLS scope rule each have exactly one definition —
   change it there and all views follow. See "Where things are defined" below.
3. **RLS is the only access gate.** Clients do no filtering; the DB returns only allowed
   rows. Any new client query is automatically scoped. Don't add app-side access checks.
4. **Test before commit.** Backend: `python tools/test_suite.py` (+ `--live`),
   `python -m backend.test_rls`, `python -m backend.test_power_users`,
   `python -m backend.test_admins`, `python -m backend.test_broker` (CORS + broker +
   admin API units). Flutter: `D:/dev/flutter/bin/flutter analyze` (must be "No issues
   found"); `flutter test`; `flutter build web`.
5. **Migrations are additive + numbered** (`backend/migrations/000N_*.sql`), idempotent
   (`if not exists` / `drop policy ... ; create`). Apply with `python -m backend.apply`.
6. **`cd /d <path>` is a cmd.exe idiom that SILENTLY FAILS in the bash tool** — use plain
   `cd D:/dev/...`. (It once ran `flutter create` at the repo root.)

## Where things are defined (change once, all views follow)

| Concept | Single source | Consumed by |
|---|---|---|
| The 13 covenant-path fields | `covenant_path/report.py` (`CovenantPathMember`) | sheet, Supabase `members`, app |
| Supabase schema / RLS | `backend/migrations/*.sql` | everything |
| Role scope rule (stake vs ward) | `backend/roles.py` + RLS policies | access everywhere |
| Golden-Hour milestones (app) | `apps/viewer/lib/golden_hour.dart` (`milestones`) | dashboard + detail |
| Golden-Hour org buckets (app) | `apps/viewer/lib/golden_hour.dart` (`orgInfo` / `responsibleOrg` / `OrgBucket`) | Golden Hour view filter chips |
| Digest milestones (email) | `backend/mailer.py` (`_DIGEST_MILESTONES`) | digest emails |
| Sheet columns | `sheets_sync/row_mapper.py` | Google Sheet |

> When adding a covenant-path field: add it in `report.py`, add a `members` column
> (migration), include it in `sheets_sync/row_mapper`, the Supabase select in
> `apps/viewer/lib/dashboard_page.dart` (`_columns`), and — if it's an integration
> milestone — `golden_hour.dart` + `mailer._DIGEST_MILESTONES`.

## Making a change uniformly across views

The viewer is **one Flutter codebase** → editing `lib/` changes web + iOS + macOS +
Android at once. To keep that true:
- Put reusable UI in **shared widgets**: `golden_hour.dart` (`GoldenHourChips`,
  `InitialsAvatar`, `milestones`, and the Golden-Hour org buckets `OrgBucket` / `orgInfo` /
  `responsibleOrg`) and `widgets/shimmer.dart` (content-shaped loading skeletons —
  `Shimmer`, `SkeletonBox`/`SkeletonLine`, `MemberListSkeleton`, `SyncSettingsSkeleton`,
  `CardSkeleton` — use these instead of a bare spinner for content areas). New views compose
  these — don't re-implement chips/rows/skeletons.
- Don't write platform-specific code in `lib/` unless guarded; the app must stay
  CORS-free (reads Supabase only) so the web build keeps working.
- After any `lib/` change: `flutter analyze` then `flutter build web` (both must pass).

## Auth & identity (how a login becomes a scope)

- Client signs in via **Supabase Auth** (email OTP / Google) — any email, no Church
  account needed. The issued JWT carries the verified email.
- **RLS** matches that email (or a bound `auth_id`) to a `user_roles` row →
  stake_leader sees the stake, ward_leader sees their unit.
- **Provider-binding trigger** (`backend/migrations/0029_provider_role_binding.sql`):
  `provision_roles` stores the LCR person UUID in `user_roles.auth_id`, but an email/Google
  login is keyed by email, and the LCR member-list endpoint that mapped UUID→email is dead.
  So a trigger on `stake_credentials` binds the enroller's verified `principal_email` to a
  stake-wide `stake_leader` row — a freshly-enrolled leader immediately sees their whole
  stake. Backend reads that need this (e.g. `auth_broker/reports.py`) match `user_roles` by
  `auth_id` **OR** verified email.
- **Power users**: `invite_power_user(email)` clones the caller's exact roles to any email
  (escalation-safe — you can only clone what you hold); recursive; audited; `revoke_power_user`.

## Secrets / config (placeholders OK; tell the user what's needed)

`.env` (local, gitignored) + GitHub Actions secrets mirror each other:
`LCR_LOGIN`, `LCR_PASSWORD`, `CP_TOKEN_KEY`, `SUPABASE_URL`, `SUPABASE_ANON_KEY`,
`SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_DB_URL` (**use the IPv4 shared pooler for CI**),
`RESEND_API_KEY`, `APP_URL`, `GOOGLE_SERVICE_ACCOUNT_JSON` (the CI secret; locally the SA file
path is `SHEETS_SERVICE_ACCOUNT`), `SPREADSHEET_ID`, plus broker/admin/Drive extras (`BROKER_URL`,
`GITHUB_TOKEN`, `GITHUB_REPO`, `WEBAUTHN_RP_ID`, `GOOGLE_OAUTH_CLIENT_ID` /
`GOOGLE_OAUTH_CLIENT_SECRET` / `GOOGLE_OAUTH_REDIRECT`). `.env.example` documents all.
