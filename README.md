# Covenant Path Platform

Collects each new member's **covenant-path progress** from the Church's LCR portal,
aggregates it at stake level into Supabase (Postgres + Row-Level Security), and presents
it across a **React web app** (`apps/web`) and **native iOS + Android** apps. Leaders sign
in with their **Church account** (or an email code) and see exactly the units their calling allows.

> New here? Read **[CLAUDE.md](CLAUDE.md)** (how to make changes safely) and
> **[PROGRESS.md](PROGRESS.md)** (what's built / what works). This file is the **map of how
> the live pieces connect**.

---

## The shape of the system

```
LCR (church data)                          ← scraped ONLY by the backend (never the client)
  └─ backend (Python) ──daily GitHub Action──► Supabase (Postgres + RLS)
       lcr_client/      okta login, API client, member profile, access matrix
       covenant_path/   the report (13 fields + rich one-work details subtree)
       sheets_sync/     Google Sheet mirror
       backend/         migrations, db, sync, roles, mailer, auth_broker
                                   │  reads (RLS-scoped by signed-in email)
  Clients ─────────────────────────┘   React web (apps/web) · native iOS (native/ios) · native Android (native/android)
       │  "Sign in with Church account" (web can't call Okta directly: CORS)
       └─────────────► auth broker (FastAPI on Render) ──► Supabase session OTP
```

**Rules of the road:** clients never touch LCR (CORS + central aggregation); access is
RLS keyed by login email or a bound LCR identity; the covenant-path fields, RLS scope rule,
sheet columns, and milestones each have exactly one definition (see CLAUDE.md → "Where
things are defined").

---

## Live deployment — the connections

| Piece | Where it lives | URL | Notes |
|---|---|---|---|
| **Web app** (React/Vite) | Cloudflare Pages | `app.membercovenantpath.org` · `covenant-path-app.pages.dev` | Built with `VITE_*` build-time env (`npm run build` in `apps/web`); deployed via `wrangler pages deploy dist` |
| **Auth broker** (FastAPI) | Render (free) | `covenant-path-broker.onrender.com` | Server-side Church login + admin/ops API; free tier sleeps → kept warm |
| **Database + Auth** | Supabase | `ntbrzjihhyvzvvzvwowq.supabase.co` | Postgres + RLS + GoTrue auth + (future) Storage for photos |
| **Daily sync** | GitHub Actions | repo `kovalyovi/covenant_path_v2` | `daily-sync.yml` 09:00 UTC: LCR → report → Sheets + Supabase |
| **Keep-warm** | Supabase pg_cron (+ optional UptimeRobot) | — | Pings broker `/health` every few min so logins don't hit a cold start (see DEPLOYMENT.md) |
| **Spreadsheet mirror** | Google Sheets | (per `SPREADSHEET_ID`) | Flat 15-column mirror, manual columns preserved on merge |

Full deploy runbook (Render blueprint, Cloudflare steps, keep-warm, admin console):
**[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)**.

---

## Configuration — what each host needs

Secrets are **never committed**. `.env` (gitignored) mirrors them locally; `.env.example`
documents every key. Public-safe values are below; secret *values* live only in each host's
settings.

**Auth broker → Render** (Environment):

| Var | Value / source |
|---|---|
| `SUPABASE_URL` | `https://ntbrzjihhyvzvvzvwowq.supabase.co` |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase → Settings → API → `service_role` (secret) |
| `ALLOWED_ORIGINS` | `https://app.membercovenantpath.org` (CORS regex also allows `*.pages.dev` + localhost) |
| `GITHUB_TOKEN` | *optional* — fine-grained PAT for the admin console's Actions panel (see below) |
| `GITHUB_REPO` | *optional* — defaults to `kovalyovi/covenant_path_v2` |

**Web build → `VITE_*` build-time env** (anon key is publishable, safe on clients; RLS gates data):

```
VITE_SUPABASE_URL=https://ntbrzjihhyvzvvzvwowq.supabase.co
VITE_SUPABASE_ANON_KEY=sb_publishable_hiAGDv7bMCm5C5O_RbGP5A_8tskAiBF
VITE_BROKER_URL=https://covenant-path-broker.onrender.com
```

**Daily sync → GitHub Actions secrets:** `LCR_LOGIN`, `LCR_PASSWORD`, `CP_TOKEN_KEY`,
`SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_DB_URL` (**use the IPv4 shared pooler for CI**),
`SUPABASE_SERVICE_ROLE_KEY`, `GOOGLE_SERVICE_ACCOUNT_JSON`, `SPREADSHEET_ID`, and (for per-stake
OAuth Drive) `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET` / `GOOGLE_OAUTH_REDIRECT`.

### `GITHUB_TOKEN` (admin console Actions panel)

Fine-grained PAT at **github.com/settings/tokens?type=beta**, scoped to **only**
`covenant_path_v2`, repository permissions: **Actions = Read and write**, **Contents =
Read-only** (Metadata read is auto). Set it as `GITHUB_TOKEN` on the Render broker. Without
it the admin console still loads — the Actions/Changelog panels and Rescrape button just hide.

---

## Features

**RLS-scoped dashboard — five tabs**, every query auto-scoped by the signed-in user's calling (no
app-side access checks). The dashboard scopes to **one selected stake** (member query + KPIs), with
a **stake switcher in the app bar** for multi-stake users. Content loads show **shimmer skeletons**
shaped like the real content, not bare spinners. Responsive: bottom nav + single column on phones;
a side rail with text-labelled items + multi-column cards on tablet/desktop.

| Tab | What it shows |
|---|---|
| **Upcoming** | Prospective baptisms as a date-rail timeline; dates already passed surface in a "needs attention" block on top. Per-unit toggle shows each ward/branch's **assigned full-time missionaries** (name chips → phone/email). |
| **Golden Hour** | **Being Taught** (investigators) + **New Members** (first-year integration milestone chips, next step highlighted). An org-responsibility filter splits converts into three colored chips — Missionaries/WML (teal), Elders Quorum (blue), Relief Society (rose) — with a responsibility subtitle when one is selected. Eligible-only completion % (ineligible members never drag the number down), tappable per category. Baptism date shows tenure — "Feb 6, 2026 (2 months 3 days)". Unit/Date grouping + asc/desc sort. |
| **Needs** | One selectable category tab per integration milestone (each with its own icon + outstanding count); the *eligible* members still missing it, with a per-unit summary, sorted by baptism date → unit. |
| **KPIs** | Line-chart cards over rolling windows anchored to today — **Month** (5 weeks), **Year** (12 months), **All** (every month, then by year past ~3 years); Month/Year show a date-range pill. Hover a point → that bucket's per-unit breakdown; tap → who. A "Golden Hour by unit" ranked card shows which unit integrates converts best. |
| **Table** | Every covenant-path field, color-coded like the master sheet: gender pill, row numbers, **per-column filters** (all/has/missing), sortable text columns. |

- **LCR-style member detail** (`apps/web/src/pages/PersonDetailPage.tsx`; native equivalents) —
  sacrament dots, friends (names + ward), priesthood / calling / ministering names, temple
  ordinances, principles-taught, self-reliance, a deep-link back to the person's LCR profile. Driven
  by the `members.details` JSONB subtree (contact PII deliberately excluded).
- **Eligibility is one source of truth** — `apps/web/src/logic/milestones.ts` `milestones` (mirrored
  in `backend/milestones.py` + the native `Logic/Milestones`): Aaronic = male & turns-12-this-year;
  Melchizedek = male & 18-now & member ≥ 1yr; ministering-assignment = turns-14; calling = turns-12.
  Stats divide by *eligible*, not everyone.
- **Settings screen** — appearance (theme), security (passkey, biometric app lock), support
  (contact / feedback), about & privacy, account (sign out). The app bar stays to ≤3 items + a
  hamburger menu of ≤5 primary actions.
- **Admin / ops console** (`apps/web/src/pages/AdminPage.tsx`, admins only) — health, freshness + counts, GitHub
  Actions runs + changelog, maintenance flows (`daily-sync.yml` dispatch), a **Diagnostics** panel
  (request success %, failing units, field parity, endpoint latency) with **"Copy for Claude"**,
  and the **Enrolled-stakes** cross-stake view with **per-stake Sync now / revoke**. Gated by
  `app_admins`; server side = broker `/admin/*`.
- **Logins** — Church account (broker → Okta IDX, MFA-aware), email OTP (invitees), **passkeys**
  (WebAuthn, passwordless), and a **broker email-OTP relay** ("Can't connect? Use backup sign-in")
  for networks that can't reach Supabase directly (e.g. some regions). Optional **biometric app
  lock** on native.
- **Power users** — `invite_power_user(email)` clones the caller's exact scope to any email
  (recursive, audited, revocable). See [docs/DELEGATED_ACCESS.md](docs/DELEGATED_ACCESS.md).
- **Observability** — `lcr_client/metrics.py` times every LCR call; each sync writes a
  `sync_diagnostics` row; structured PII-safe events ship to **Axiom**; uncaught client errors go
  to **Sentry** (no PII) and the broker `/log`. `tools/endpoint_probe.py` characterises LCR's
  per-endpoint health/rate limits.
- **Email digests + invitations** via Resend.

---

## Multi-stake support

The platform serves **many stakes at once**, each isolated end-to-end:

- **Access** — RLS scopes every read by the signed-in user's LCR calling (or a bound identity).
  Stake leaders see their stake; ward leaders see their unit; clerks/exec-secs are on the
  always-allowed calling list. Roles are auto-provisioned from LCR each sync (`backend/roles.py`).
- **Delegated credentials** — Church sign-in always enrolls the stake (the consent note is inline
  on the login screen; the old "Keep my stake synced" checkbox is gone): the leader's LCR session
  is stored **envelope-encrypted** (`backend/credentials.py`, `CP_TOKEN_KEY`) and their verified
  email is bound to a stake-wide `stake_leader` role (trigger, migration 0029) so they see their
  stake. The daily job mints from the stored session (three-tier renewal: stored appSession → Okta
  re-SSO → OAuth refresh). Revoke (Settings → Sync settings) pauses it. See
  [docs/DELEGATED_ACCESS.md](docs/DELEGATED_ACCESS.md).
- **Per-stake sync jobs** — `daily-sync.yml` is a dynamic matrix: a `prepare` job lists the
  enrolled stakes and fans out **one isolated job per stake** (own logs, independent pass/fail).
  `daily_sync.py --stake <unit>` runs exactly one; `--only <unit>` (via the workflow `stake` input)
  powers the OPS per-stake "Sync now".
- **Per-stake spreadsheets** — each stake gets its **own** Google Sheet, shared read-only with that
  stake's leadership (from the synced roster). The shared master sheet is reserved for the
  operator's own stake — other stakes never mingle into it (they skip Sheets if Drive can't create
  their own). Needs the Drive API enabled on the service account.
- **Cross-stake ops** — the admin console's Enrolled-stakes panel shows every stake's enrollment,
  coverage, freshness, member count + per-stake Sync/revoke.
- **Roadmap** — per-stake Google **OAuth** so each stake fully owns its sheet in *its* Drive (M7).

---

## Local development

```powershell
# 1. Backend deps
pip install -r requirements.txt

# 2. Apply DB migrations (needs SUPABASE_DB_URL in .env)
python -m backend.apply

# 3. Run a sync (LCR → report → Supabase). --with-profile fills baptism/recommend/etc.
python scripts/daily_sync.py --mode self --with-profile --supabase

# 4. Broker locally
uvicorn backend.auth_broker.app:app --reload --port 8787

# 5. Web app locally (React + Vite). Put the VITE_* values in apps/web/.env.local:
#   VITE_SUPABASE_URL=https://ntbrzjihhyvzvvzvwowq.supabase.co
#   VITE_SUPABASE_ANON_KEY=sb_publishable_hiAGDv7bMCm5C5O_RbGP5A_8tskAiBF
#   VITE_BROKER_URL=http://localhost:8787
cd apps/web
npm install
npm run dev            # Vite dev server (http://localhost:5173)
npm run build          # production bundle → apps/web/dist/ (what Cloudflare Pages serves)

# 6. Native apps (iOS Swift / Android Kotlin) build in CI — see native/PARITY.md.
#    The build contracts run in build-native-ios.yml / build-native-android.yml; locally
#    open native/ios in Xcode or native/android in Android Studio.
```

### Tests (run before committing)

```
python tools/test_suite.py            # offline (+ --live)
python -m backend.test_rls            # RLS scoping
python -m backend.test_power_users    # invite/clone/revoke
python -m backend.test_admins         # app_admins model
python -m backend.test_broker         # CORS + broker + admin API units
cd apps/web && npm run typecheck      # web type check
cd apps/web && npm run test           # web unit tests (vitest)
cd apps/web && npm run e2e            # web end-to-end (Playwright, mocked edges)
```

---

## Gotchas worth knowing (hard-won)

- **CORS**: Starlette does **not** glob `allow_origins` (exact match only). The broker uses
  `allow_origin_regex` to cover `*.membercovenantpath.org`, `*.pages.dev`, and localhost —
  locked in by `backend/test_broker.py`. Adding a new origin? It probably already matches.
- **Render cold start**: free tier sleeps after ~15 min; the first login then fails "Failed
  to fetch" (holding page has no CORS header). Mitigated by in-app retry (~60s, "waking up…")
  + keep-warm (Supabase pg_cron, optional UptimeRobot, on `/health`).
- **Supabase JWTs are asymmetric** here, so we can't mint custom JWTs. The broker uses the
  Admin API `generate_link` → an 8-char `email_otp` the app verifies with `OtpType.email`.
- **`is_admin()` must be `SECURITY DEFINER`** — otherwise the `app_admins` RLS policy that
  calls it recurses infinitely (stack overflow). Same pattern for any helper that reads the
  table its own policy guards.
- **CI database URL**: use the **IPv4 shared pooler** (`...pooler.supabase.com:5432`) for
  GitHub Actions — the direct `db.<ref>.supabase.co` host is IPv6-only and fails on runners.
- **Cloudflare Pages**: `wrangler`'s auto-create-project can fail with API `code: 8000000` —
  create the `covenant-path-app` project once in the dashboard, then `wrangler pages deploy`.
- **LCR one-work details** use the person's `id`, **not** `personUuid` (the latter 500s). The
  endpoint returns ~198 fields; we keep the progress subtree in `members.details`.
- **LCR endpoint health** (probe-confirmed, `tools/endpoint_probe.py`): it's **not** rate-limiting.
  `progress-record` is slow (~10.8s p50) and 500s ~38% — the report retries it **5×** with backoff
  then skips that unit (upserts are non-destructive, so it keeps prior rows). `member-list`
  (`/api/umlu/report/member-list`) currently **404s for every unit** (LCR moved/removed it) — it only
  enriched sex/birth, which the profile fetch covers, so one attempt + graceful skip.
- **Profile action ids are build-specific** — `member_profile` self-heals via
  `action_discovery` (a brief Playwright run) when LCR redeploys and an id goes stale.

---

## Doc map

| Doc | What |
|---|---|
| [CLAUDE.md](CLAUDE.md) | Rules + architecture; read before editing |
| [PROGRESS.md](PROGRESS.md) | Living status log (what's built / works / doesn't) |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | Broker + web app + keep-warm + admin-console deploy runbook |
| [docs/DECISIONS.md](docs/DECISIONS.md) | ADR log — the *why* behind the design |
| [docs/DELEGATED_ACCESS.md](docs/DELEGATED_ACCESS.md) | Power users + delegated-access + security model |
| [docs/CUSTOM_API_KEYS.md](docs/CUSTOM_API_KEYS.md) | Per-stake custom API keys |
| [docs/LOGGING_SETUP.md](docs/LOGGING_SETUP.md) | Axiom + Sentry setup (free tiers, PII-safe) |
| [docs/M7_OAUTH_DRIVE.md](docs/M7_OAUTH_DRIVE.md) | Per-stake Google OAuth Drive — design + GCP prereq |
| [backend/auth_broker/README.md](backend/auth_broker/README.md) | Broker internals + security notes |
| [apps/web/README.md](apps/web/README.md) | React web app structure + shared logic |
| [native/PARITY.md](native/PARITY.md) | Native iOS/Android parity map + build contracts |
