# Failover runbook — providers & how to repoint each (#67 §4)

The platform runs entirely on free tiers. This is the "if a tier squeezes us" playbook: what each
service does, its limit, **how to repoint it** (the one config to change), and the fallback. The
design goal (already mostly true) is that **only Supabase is a hard dependency** — everything else
is a config change, not a rewrite. See `docs/STRATEGY.md` §4 for the rationale.

## Providers at a glance

| Service | Role | Free-tier limit | Repoint via | Swap difficulty |
|---|---|---|---|---|
| **Supabase** | Postgres + Auth + RLS (system of record) | 500 MB DB; **pauses after ~1 wk idle** (daily sync keeps it warm) | `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_DB_URL` | **High** |
| **Render** | auth broker (FastAPI) | sleeps after 15 min idle | `BROKER_URL` (app) + redeploy container elsewhere | Low |
| **Cloudflare Pages** | viewer hosting | 500 builds/mo | `CLOUDFLARE_*` secrets + `projectName` | Low |
| **GitHub Actions** | daily sync + deploy CI | 2,000 min/mo private | move workflows to any cron/CI | Low |
| **Resend** | email (digests, invites, reports, handoffs) | 3,000/mo, 100/day | `RESEND_API_KEY` **or** `SMTP_*` | Low (SMTP fallback built in) |
| **Google Sheets** | coarse per-stake export (optional) | free | `SPREADSHEET_ID` + service account | Low (optional) |

## Repoint recipes

### Email — Resend → SMTP (or another provider)
`backend/mailer.py` is provider-agnostic: it prefers `RESEND_API_KEY`, else falls back to SMTP.
To switch, **unset `RESEND_API_KEY`** and set `SMTP_HOST/SMTP_PORT/SMTP_USER/SMTP_PASS/SMTP_FROM`
(Gmail App Password, Brevo, etc. — all work without owning a domain). No code change. The same
vars are read by the daily-sync and weekly-reminders workflows and the broker.

### Auth broker — Render → Fly/Railway/any container host
The broker is a plain FastAPI container (`Dockerfile` at repo root, no browser, no DB). Deploy it
anywhere, then set the app's **`BROKER_URL`** (`--dart-define` for the viewer build; the GitHub
repo variable `BROKER_URL` for keep-warm). Its env: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`,
`CP_TOKEN_KEY` (now required — enrollment encryption), `ALLOWED_ORIGINS`, `GITHUB_TOKEN`,
`RESEND_API_KEY`. CORS already allows `*.pages.dev`, `*.membercovenantpath.org`, localhost.

### Viewer host — Cloudflare Pages → any static host
`flutter build web` output is plain static files. Any host (Netlify, GitHub Pages, S3+CloudFront)
serves it. Keep the `web/_headers` cache rules (or replicate them) so `index.html` /
`flutter_service_worker.js` revalidate. Update `deploy-web.yml` (or replace it) for the new host.

### CI — GitHub Actions → any scheduler
Three workflows: `daily-sync.yml` (the only one that needs the LCR/Supabase/Sheets secrets +
runs the scrape), `weekly-reminders.yml`, `deploy-web.yml`. Each is a thin wrapper around a
`python scripts/*.py` or `flutter build`. Port to any cron host with the same env (the secrets
checklist is in `DEPLOYMENT.md`).

## The hard one — Supabase (Postgres + Auth + RLS)

This is the only deep dependency: RLS *is* the access model (ADR-001/0002), Auth issues the app
session, and the REST API is the broker's data path. Mitigations already in place + the migration
path if we ever must move:

- **Idle-pause (the real near-term risk):** the daily sync writes every morning, which keeps the
  project warm. If the sync ever stops for a week, the DB pauses and the app reads fail until you
  un-pause it in the Supabase dashboard. **Keep the daily sync green.**
- **Portability:** the schema is **vendor-neutral SQL** (`backend/migrations/*.sql`, plain Postgres
  + `pgcrypto`). It applies to any Postgres. The access model is standard RLS policies. So a move to
  **self-hosted Supabase (OSS)** or **bare Postgres + PostgREST + an auth shim** is a re-point, not a
  redesign: change `SUPABASE_URL`/keys/`SUPABASE_DB_URL`, re-run `python -m backend.apply`, re-seed
  the owner admin row. The viewer talks to Supabase only through `supabase_flutter` + the broker's
  REST calls — concentrated enough to swap the base URL.
- **Auth is the stickiest piece:** GoTrue (Supabase Auth) issues the JWT RLS keys off. Self-hosting
  Supabase keeps GoTrue; going fully bare-Postgres would need an auth replacement that mints
  RLS-compatible JWTs. Defer until actually forced.

## When to actually act

Free tiers are comfortable at current scale (one operator stake + a couple delegated stakes).
**Don't pre-migrate.** Trigger this runbook only when a concrete limit bites: Supabase storage
near 500 MB, Resend over 3k/mo, or Actions over 2k min/mo. Each row above is an independent,
low-risk repoint — do the one that's squeezed, leave the rest.
