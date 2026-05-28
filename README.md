# Covenant Path Platform

Collects each new member's **covenant-path progress** from the Church's LCR portal,
aggregates it at stake level into Supabase (Postgres + Row-Level Security), and presents
it in one Flutter app (web / iOS / macOS / Android). Leaders sign in with their **Church
account** (or an email code) and see exactly the units their calling allows.

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
  Flutter viewer (apps/viewer) ────┘   ONE codebase → web + iOS + macOS + Android
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
| **Viewer** (Flutter web) | Cloudflare Pages | `app.membercovenantpath.org` · `covenant-path-app.pages.dev` | Built with `--dart-define`; deployed via `wrangler pages deploy` or dashboard upload |
| **Auth broker** (FastAPI) | Render (free) | `covenant-path-broker.onrender.com` | Server-side Church login + admin/ops API; free tier sleeps → kept warm |
| **Database + Auth** | Supabase | `ntbrzjihhyvzvvzvwowq.supabase.co` | Postgres + RLS + GoTrue auth + (future) Storage for photos |
| **Daily sync** | GitHub Actions | repo `kovalyovi/covenant_path_v2` | `daily-sync.yml` 09:00 UTC: LCR → report → Sheets + Supabase |
| **Keep-warm** | GitHub Actions + UptimeRobot | — | Pings broker `/health` so logins don't hit a cold start |
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

**Viewer build → `--dart-define`** (anon key is publishable, safe on clients; RLS gates data):

```
SUPABASE_URL=https://ntbrzjihhyvzvvzvwowq.supabase.co
SUPABASE_ANON_KEY=sb_publishable_hiAGDv7bMCm5C5O_RbGP5A_8tskAiBF
BROKER_URL=https://covenant-path-broker.onrender.com
```

**Daily sync → GitHub Actions secrets:** `LCR_LOGIN`, `LCR_PASSWORD`, `CP_TOKEN_KEY`,
`SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_DB_URL` (**use the IPv4 shared pooler for CI**),
`GOOGLE_SERVICE_ACCOUNT_JSON`, `SPREADSHEET_ID`.

### `GITHUB_TOKEN` (admin console Actions panel)

Fine-grained PAT at **github.com/settings/tokens?type=beta**, scoped to **only**
`covenant_path_v2`, repository permissions: **Actions = Read and write**, **Contents =
Read-only** (Metadata read is auto). Set it as `GITHUB_TOKEN` on the Render broker. Without
it the admin console still loads — the Actions/Changelog panels and Rescrape button just hide.

---

## Features

- **RLS-scoped dashboard** — Golden Hour view + spreadsheet view; every query is auto-scoped
  by the signed-in user's calling. No app-side access checks.
- **LCR-style member detail** (`person_detail_page.dart`) — sacrament-attendance dots, friends
  (names + ward), priesthood / calling / ministering names, temple ordinances & experiences,
  principles-taught progress, self-reliance. Driven by the `members.details` JSONB subtree the
  sync keeps (contact PII deliberately excluded).
- **Admin / ops console** (`admin_page.dart`, gear icon, admins only) — system health, data
  freshness + row counts, GitHub Actions runs + changelog, **Rescrape + repopulate** (dispatch
  `daily-sync.yml`), re-run, and invite/revoke admins (escalation-safe). Server side =
  broker `/admin/*`; gated by the `app_admins` table.
- **Dual login** — Church account (broker → Okta IDX, MFA-aware) or email OTP (invitees).
- **Power users** — `invite_power_user(email)` clones the caller's exact scope to any email
  (recursive, audited, revocable). See [docs/DELEGATED_ACCESS.md](docs/DELEGATED_ACCESS.md).
- **Email digests + invitations** via Resend.

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

# 5. Viewer locally
cd apps/viewer
D:/dev/flutter/bin/flutter run -d chrome `
  --dart-define=SUPABASE_URL=https://ntbrzjihhyvzvvzvwowq.supabase.co `
  --dart-define=SUPABASE_ANON_KEY=sb_publishable_hiAGDv7bMCm5C5O_RbGP5A_8tskAiBF `
  --dart-define=BROKER_URL=http://localhost:8787
```

### Tests (run before committing)

```
python tools/test_suite.py            # offline (+ --live)
python -m backend.test_rls            # RLS scoping
python -m backend.test_power_users    # invite/clone/revoke
python -m backend.test_admins         # app_admins model
python -m backend.test_broker         # CORS + broker + admin API units
cd apps/viewer && D:/dev/flutter/bin/flutter analyze   # must be "No issues found"
cd apps/viewer && D:/dev/flutter/bin/flutter test
```

---

## Gotchas worth knowing (hard-won)

- **CORS**: Starlette does **not** glob `allow_origins` (exact match only). The broker uses
  `allow_origin_regex` to cover `*.membercovenantpath.org`, `*.pages.dev`, and localhost —
  locked in by `backend/test_broker.py`. Adding a new origin? It probably already matches.
- **Render cold start**: free tier sleeps after ~15 min; the first login then fails "Failed
  to fetch" (holding page has no CORS header). Mitigated by in-app retry (~60s, "waking up…")
  + keep-warm (GitHub workflow + UptimeRobot on `/health`).
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
- **LCR transient 500s**: `progress-record` occasionally 500s for a unit. The report retries
  3× then skips that unit, and upserts are non-destructive, so a skipped ward keeps its prior
  rows (a later sync fills it in).
- **Profile action ids are build-specific** — `member_profile` self-heals via
  `action_discovery` (a brief Playwright run) when LCR redeploys and an id goes stale.

---

## Doc map

| Doc | What |
|---|---|
| [CLAUDE.md](CLAUDE.md) | Rules + architecture; read before editing |
| [PROGRESS.md](PROGRESS.md) | Living status log (what's built / works / doesn't) |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | Broker + viewer + keep-warm + admin-console deploy runbook |
| [docs/DECISIONS.md](docs/DECISIONS.md) | ADR log — the *why* behind the design |
| [docs/DELEGATED_ACCESS.md](docs/DELEGATED_ACCESS.md) | Power users + delegated-access + security model |
| [docs/CUSTOM_API_KEYS.md](docs/CUSTOM_API_KEYS.md) | Per-stake custom API keys |
| [backend/auth_broker/README.md](backend/auth_broker/README.md) | Broker internals + security notes |
| [apps/viewer/ARCHITECTURE.md](apps/viewer/ARCHITECTURE.md) | Viewer structure + shared widgets |
