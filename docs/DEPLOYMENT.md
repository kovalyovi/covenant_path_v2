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
gates data). Build locally, then upload.

```powershell
cd D:/dev/covenant_path_v2/apps/viewer
D:/dev/flutter/bin/flutter build web --release `
  --dart-define=SUPABASE_URL=https://ntbrzjihhyvzvvzvwowq.supabase.co `
  --dart-define=SUPABASE_ANON_KEY=sb_publishable_hiAGDv7bMCm5C5O_RbGP5A_8tskAiBF `
  --dart-define=BROKER_URL=https://covenant-path-broker.onrender.com
```
Output: `apps/viewer/build/web`.

Deploy (either):
- **Dashboard:** Cloudflare → Workers & Pages → Create → Pages → *Upload assets* → name
  `covenant-path-app` → drag the `build/web` folder → Deploy.
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
error. Pin a stable combo: AGP **8.7.3** + Kotlin **2.1.0** in `android/settings.gradle.kts`, and
Gradle **8.11.1** in `android/gradle/wrapper/gradle-wrapper.properties`.

---

## 3. Keep the broker warm (avoid cold-start login failures)

Render free sleeps after ~15 min idle; the first request after a sleep hits a holding page
with **no CORS header**, so the browser reports `Failed to fetch`. Two mitigations, both on:

- **In-app:** `broker_client.dart` retries network failures across ~60s and shows
  "Waking up the sign-in service…", so a cold start resolves itself instead of erroring.
- **Keep-warm pings:**
  - *Free backstop (already committed):* `.github/workflows/keep-broker-warm.yml` pings
    `/health` every 10 min. GitHub cron is best-effort (can be delayed), so treat it as a
    backstop, not a guarantee.
  - *Reliable (recommended): **UptimeRobot*** — free, pings every 5 min:
    1. uptimerobot.com → sign up → **+ New monitor**.
    2. Type **HTTP(s)**, URL `https://covenant-path-broker.onrender.com/health`,
       interval **5 minutes**.
    3. Save. It both keeps the broker awake and emails you if it ever goes down.

If the broker URL ever changes, set repo variable `BROKER_URL` (Settings → Secrets and
variables → Actions → Variables) and update the UptimeRobot monitor + the viewer's
`--dart-define=BROKER_URL`.

---

## Secrets checklist

| Where | Needs |
|---|---|
| Render (broker) | `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `ALLOWED_ORIGINS`, `GITHUB_TOKEN` *(optional, admin console)* |
| GitHub Actions (daily sync) | `LCR_LOGIN`, `LCR_PASSWORD`, `CP_TOKEN_KEY`, `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_DB_URL` (IPv4 pooler), `GOOGLE_SERVICE_ACCOUNT_JSON`, `SPREADSHEET_ID` |
| Viewer build | `--dart-define`: `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `BROKER_URL` |

Never commit any of these — `.env` mirrors them locally and is gitignored.
