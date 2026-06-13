# Deployment

How the two deployable pieces go live and stay healthy:

- **Auth broker** (`backend/auth_broker`) — small FastAPI server for "Sign in with your
  Church account" on the web. Hosted on **Render** (free).
- **Web app** (`apps/web`) — the **React (Vite)** app. Hosted on **Cloudflare Pages** (free)
  at `app.membercovenantpath.org`. (The native iOS/Android apps build in CI — see §2b.)

The daily data sync is separate and runs in **GitHub Actions** (`.github/workflows/daily-sync.yml`).

---

## 1. Auth broker → Render

A `render.yaml` blueprint is committed at the repo root.

1. Render → **New → Blueprint** → pick this repo → it detects `render.yaml`.
2. Set the secret env vars (the blueprint marks them `sync:false`):
   - `SUPABASE_URL` = `https://ntbrzjihhyvzvvzvwowq.supabase.co`
   - `SUPABASE_SERVICE_ROLE_KEY` = (Supabase → Settings → API → `service_role`)
   - `ALLOWED_ORIGINS` is prefilled to the custom domain; CORS also allows `*.pages.dev`
     and localhost via a built-in regex, so you don't have to list every origin.
   - `GITHUB_TOKEN` *(optional)* — enables the admin console's Actions panel + flow
     buttons (rescrape, re-run). Without it the console still loads but those are hidden.
     See the admin-console section below for the exact PAT scopes.
3. **Apply.** Confirm `https://<service>.onrender.com/health` returns `{"ok":true}`.

Auto-deploy: Render redeploys on every push to `main` (blueprint default). To force one,
use **Manual Deploy → Deploy latest commit**.

Local run: `uvicorn backend.auth_broker.app:app --reload --port 8787`.

### Admin / ops console

The app shows an **Admin** button (gear) to anyone in the `app_admins` table. It calls the
broker's `/admin/*` endpoints (the broker verifies your Supabase token belongs to an admin
using the service-role key) and surfaces: system health, data freshness + row counts,
recent GitHub Actions runs, the commit changelog, a **Rescrape + repopulate** button
(dispatches `daily-sync.yml` → re-scrape LCR → Google Sheets + Supabase), per-run **re-run**,
and admin invite/revoke (escalation-safe; you can't revoke yourself).

To enable the Actions/flow features, set `GITHUB_TOKEN` on the broker to a **fine-grained
PAT** (GitHub → Settings → Developer settings → Fine-grained tokens), scoped to **only the
`covenant_path_v2` repo**, with these **Repository permissions**:

| Permission | Access | Why |
|---|---|---|
| **Actions** | Read and write | list runs, dispatch `daily-sync.yml`, re-run failed runs |
| **Contents** | Read-only | read the commit changelog |
| **Metadata** | Read-only | mandatory baseline (auto-selected) |

Override the repo with `GITHUB_REPO` env (default `kovalyovi/covenant_path_v2`). The token
is only ever held server-side on the broker — never shipped to the app.

---

## 2. Web app → Cloudflare Pages

The React app is **Vite**; config is baked in at build time via `VITE_*` env vars (the anon
key is safe on clients; RLS gates data).

### Auto-deploy (default — GitHub Actions)

`.github/workflows/deploy-web.yml` builds `apps/web` (`npm ci && npm run build`) and deploys
the `dist/` output to Cloudflare Pages with **wrangler** on **every push to `main` that
touches `apps/web/**`** (and on manual `workflow_dispatch`). Backend-only commits skip the
build via the `paths` filter. After deploy it runs `npm run smoke` against the live site to
confirm the shell + every lazy chunk serve (catches the "failed to fetch dynamically imported
module" class of breakage).

The Pages project stays in **direct-upload** mode (wrangler) — do **not** also connect git in
the Cloudflare dashboard or you'll get competing deploys.

Required GitHub secrets (Settings → Secrets and variables → Actions):
`CLOUDFLARE_API_TOKEN` (Edit Cloudflare Pages template), `CLOUDFLARE_ACCOUNT_ID`,
`SUPABASE_URL`, `SUPABASE_ANON_KEY`, `BROKER_URL`, *optional* `SENTRY_DSN` (web error
reporting) and `APP_URL` (the smoke-test target; defaults to production). The
`--project-name` in the workflow must match the Pages project (`covenant-path-app`).

Force a deploy: GitHub → Actions → "Deploy web app to Cloudflare Pages" → Run workflow.

### Manual deploy (fallback)

```powershell
cd D:/dev/covenant_path_v2/apps/web
$env:VITE_SUPABASE_URL = "https://ntbrzjihhyvzvvzvwowq.supabase.co"
$env:VITE_SUPABASE_ANON_KEY = "sb_publishable_hiAGDv7bMCm5C5O_RbGP5A_8tskAiBF"
$env:VITE_BROKER_URL = "https://covenant-path-broker.onrender.com"
npm ci
npm run build
npx wrangler@4 pages deploy dist --project-name=covenant-path-app --branch=main
```
(`--branch=main` marks it a production deployment. Create the Pages project once in the
dashboard first — wrangler's auto-create can fail with Cloudflare API `code: 8000000`.)

Custom domain: Pages project → **Custom domains** → add `app.membercovenantpath.org`.
DNS is already at Cloudflare, so the record + HTTPS are provisioned automatically.

> The broker's CORS allows both `*.pages.dev` and `app.membercovenantpath.org`, so login
> works from the Pages URL and the custom domain.

---

## 2b. Native apps (iOS + Android)

The native apps are **Swift (`native/ios`)** and **Kotlin (`native/android`)** — they build
in CI, not locally:

- **iOS** — `.github/workflows/build-native-ios.yml` produces an unsigned `.ipa` artifact.
  Install on a device without a Mac/Apple-developer account via AltStore/Sideloadly on
  Windows — step-by-step in **`docs/IOS_SIDELOAD.md`** (free Apple ID, 7-day refresh).
- **Android** — `.github/workflows/build-native-android.yml` runs the unit tests and produces
  a debug APK artifact; download it from the run and install (enable "install from unknown
  sources").

Both read the same backend (Supabase + the broker); there's no separate per-app deploy step.

---

## 3. Keep the broker warm (avoid cold-start login failures)

Render free sleeps after ~15 min idle; the first request after a sleep hits a holding page
with **no CORS header**, so the browser reports `Failed to fetch`. Two mitigations, both on:

- **In-app:** the web broker client (`apps/web/src/lib/broker.ts`) retries network failures
  across ~60s and shows "Waking up the sign-in service…", so a cold start resolves itself
  instead of erroring; it also warms `/health` on app load.
- **Keep-warm pings:**
  - *Primary (live since 2026-06-09): **Supabase pg_cron*** — migration `0042_login_fast_lane.sql`
    schedules cron job **`keep-broker-warm`** to `net.http_get` the broker `/health` every
    **4 minutes** from Postgres. Unlike GitHub cron it fires on time. Inspect with
    `select * from cron.job;` and recent firings in `cron.job_run_details`. This is the sole
    keep-warm now — the old `keep-broker-warm.yml` GitHub-cron backstop was removed
    2026-06-13 (it fired only every 2–4h, too slow to prevent a 15-min Render sleep).
  - *Optional extra: **UptimeRobot*** — free, pings every 5 min and also emails you if the
    broker is ever down: uptimerobot.com → **+ New monitor** → HTTP(s),
    `https://covenant-path-broker.onrender.com/health`, interval 5 min.

If the broker URL ever changes, set the `BROKER_URL` GitHub secret (Settings → Secrets and
variables → Actions) and update the UptimeRobot monitor; the web build picks it up as
`VITE_BROKER_URL` on the next deploy.

---

## Secrets checklist

| Where | Needs |
|---|---|
| Render (broker) | `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `CP_TOKEN_KEY` (enrollment encryption), `ALLOWED_ORIGINS`; *optional:* `GITHUB_TOKEN` + `GITHUB_REPO` (admin console), `WEBAUTHN_RP_ID` (passkeys), `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET` / `GOOGLE_OAUTH_REDIRECT` (per-stake Drive), `RESEND_API_KEY` (reports/contact) |
| GitHub Actions (daily sync) | `LCR_LOGIN`, `LCR_PASSWORD`, `CP_TOKEN_KEY`, `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_DB_URL` (IPv4 pooler), `GOOGLE_SERVICE_ACCOUNT_JSON`, `SPREADSHEET_ID`; *optional (per-stake OAuth Drive):* `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET` / `GOOGLE_OAUTH_REDIRECT` |
| GitHub Actions (deploy-web) | `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`, `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `BROKER_URL`; *optional:* `SENTRY_DSN`, `APP_URL` |
| Web build (Vite) | `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`, `VITE_BROKER_URL`; *optional:* `VITE_SENTRY_DSN` |

Never commit any of these — `.env` mirrors them locally and is gitignored.
