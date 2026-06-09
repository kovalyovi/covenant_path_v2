# Deployment

How the two deployable pieces go live and stay healthy:

- **Auth broker** (`backend/auth_broker`) — small FastAPI server for "Sign in with your
  Church account" on the web. Hosted on **Render** (free).
- **Viewer** (`apps/viewer`) — the Flutter web app. Hosted on **Cloudflare Pages** (free)
  at `app.membercovenantpath.org`.

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

## 2. Viewer → Cloudflare Pages

Config is baked at build time via `--dart-define` (the anon key is safe on clients; RLS
gates data).

### Auto-deploy (default — GitHub Actions)

`.github/workflows/deploy-web.yml` builds the Flutter web app and deploys it to Cloudflare
Pages on **every push to `main` that touches `apps/viewer/**`** (and on manual
`workflow_dispatch`). Backend-only commits skip the build via the `paths` filter.

Why GitHub Actions and not Cloudflare's native git integration: Cloudflare's build image
has no Flutter SDK, so the native integration would need a brittle per-build SDK-download
script. The Actions runner uses `subosito/flutter-action` (SDK cached) — the standard,
reliable path. The Pages project stays in **direct-upload** mode; do **not** also connect
git in the Cloudflare dashboard or you'll get competing deploys.

Required GitHub secrets (Settings → Secrets and variables → Actions):
`CLOUDFLARE_API_TOKEN` (Edit Cloudflare Pages template), `CLOUDFLARE_ACCOUNT_ID`,
`SUPABASE_URL`, `SUPABASE_ANON_KEY`, `BROKER_URL`. The `projectName` in the workflow must
match the Pages project (`covenant-path-app`).

Force a deploy: GitHub → Actions → "Deploy web app to Cloudflare Pages" → Run workflow.

### Manual deploy (fallback)

```powershell
cd D:/dev/covenant_path_v2/apps/viewer
D:/dev/flutter/bin/flutter build web --release `
  --dart-define=SUPABASE_URL=https://ntbrzjihhyvzvvzvwowq.supabase.co `
  --dart-define=SUPABASE_ANON_KEY=sb_publishable_hiAGDv7bMCm5C5O_RbGP5A_8tskAiBF `
  --dart-define=BROKER_URL=https://covenant-path-broker.onrender.com
```
Output: `apps/viewer/build/web`. Then either:
- **Dashboard:** Cloudflare → Workers & Pages → `covenant-path-app` → *Upload assets* →
  drag the `build/web` folder → Deploy.
- **CLI:** `npx wrangler pages deploy build/web --project-name covenant-path-app --branch main`
  (create the project once in the dashboard first — wrangler's auto-create can fail with
  Cloudflare API `code: 8000000`).

Custom domain: Pages project → **Custom domains** → add `app.membercovenantpath.org`.
DNS is already at Cloudflare, so the record + HTTPS are provisioned automatically.

> The broker's CORS allows both `*.pages.dev` and `app.membercovenantpath.org`, so login
> works from the Pages URL and the custom domain.

---

## 2b. Android app (APK)

Same codebase, same `--dart-define` config (pointed at the prod broker):

```powershell
cd D:/dev/covenant_path_v2/apps/viewer
D:/dev/flutter/bin/flutter build apk --release `
  --dart-define=SUPABASE_URL=https://ntbrzjihhyvzvvzvwowq.supabase.co `
  --dart-define=SUPABASE_ANON_KEY=sb_publishable_hiAGDv7bMCm5C5O_RbGP5A_8tskAiBF `
  --dart-define=BROKER_URL=https://covenant-path-broker.onrender.com
```
Output: `apps/viewer/build/app/outputs/flutter-apk/app-release.apk`. Copy it to an Android
device and install (enable "install from unknown sources"). For a smaller per-device download
use `--split-per-abi`; for the Play Store build an `.aab` (`flutter build appbundle`).

**Toolchain note:** the generated `android/` is gitignored. If you re-run `flutter create`, it
may scaffold a bleeding-edge AGP (9.x) that breaks plugins with a `DefaultAndroidSourceSet` cast
error. Pin a stable combo: AGP **8.9.1** + Kotlin **2.1.0** in `android/settings.gradle.kts`, and
Gradle **8.11.1** in `android/gradle/wrapper/gradle-wrapper.properties`. (AGP 8.7.3 is too OLD for
`app_links 7.1.0` — a transitive dep of `supabase_flutter` — and throws the SAME cast error; 8.9.1
is the sweet spot: new enough for the plugins, short of the 9.x break.)

**Two manifest edits the release build needs** (`android/app/src/main/AndroidManifest.xml`, also
regenerated by `flutter create` so re-apply after a regen):
- Add **`<uses-permission android:name="android.permission.INTERNET"/>`** above `<application>`.
  Flutter only auto-adds INTERNET to the *debug* manifest; without it the **release** APK has no
  network and the app can't reach Supabase or the broker (blank/"no config" screen).
- Set `android:label="Covenant Path"` (default scaffold uses `covenant_path_viewer`).

---

## 3. Keep the broker warm (avoid cold-start login failures)

Render free sleeps after ~15 min idle; the first request after a sleep hits a holding page
with **no CORS header**, so the browser reports `Failed to fetch`. Two mitigations, both on:

- **In-app:** `broker_client.dart` retries network failures across ~60s and shows
  "Waking up the sign-in service…", so a cold start resolves itself instead of erroring.
- **Keep-warm pings:**
  - *Primary (live since 2026-06-09): **Supabase pg_cron*** — migration `0042_login_fast_lane.sql`
    schedules cron job **`keep-broker-warm`** to `net.http_get` the broker `/health` every
    **4 minutes** from Postgres. Unlike GitHub cron it fires on time. Inspect with
    `select * from cron.job;` and recent firings in `cron.job_run_details`.
  - *Free backstop:* `.github/workflows/keep-broker-warm.yml` pings `/health` every 5 min on
    paper — measured firing every **2–4 hours** (GitHub cron is best-effort). Backstop only.
  - *Optional extra: **UptimeRobot*** — free, pings every 5 min and also emails you if the
    broker is ever down: uptimerobot.com → **+ New monitor** → HTTP(s),
    `https://covenant-path-broker.onrender.com/health`, interval 5 min.

If the broker URL ever changes, set repo variable `BROKER_URL` (Settings → Secrets and
variables → Actions → Variables) and update the UptimeRobot monitor + the viewer's
`--dart-define=BROKER_URL`.

---

## Secrets checklist

| Where | Needs |
|---|---|
| Render (broker) | `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `CP_TOKEN_KEY` (enrollment encryption), `ALLOWED_ORIGINS`; *optional:* `GITHUB_TOKEN` + `GITHUB_REPO` (admin console), `WEBAUTHN_RP_ID` (passkeys), `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET` / `GOOGLE_OAUTH_REDIRECT` (per-stake Drive), `RESEND_API_KEY` (reports/contact) |
| GitHub Actions (daily sync) | `LCR_LOGIN`, `LCR_PASSWORD`, `CP_TOKEN_KEY`, `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_DB_URL` (IPv4 pooler), `GOOGLE_SERVICE_ACCOUNT_JSON`, `SPREADSHEET_ID`; *optional (per-stake OAuth Drive):* `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET` / `GOOGLE_OAUTH_REDIRECT` |
| GitHub Actions (deploy-web) | `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`, `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `BROKER_URL` |
| Viewer build | `--dart-define`: `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `BROKER_URL` |

Never commit any of these — `.env` mirrors them locally and is gitignored.
