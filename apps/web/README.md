# Covenant Path — React web app (`apps/web`)

A **web-only** React rebuild of the Flutter web viewer (`apps/viewer`), with full UI + functionality
parity. Like the Flutter app it is **CORS-free**: it reads **Supabase** directly (RLS-scoped to the
signed-in user — the client does no access filtering) and the **auth broker** (`backend/auth_broker`)
using the same endpoints. No backend changes.

> Independent tool · not an official product of The Church of Jesus Christ of Latter-day Saints.

## Stack

- **Vite + React 18 + TypeScript**
- **React Router v7** (mirrors the Flutter `go_router` map)
- **@supabase/supabase-js** (auth + RLS-scoped reads)
- **@tanstack/react-query** (client cache wrapper)
- **Recharts** (KPI trend lines)
- **@sentry/react** + **web-vitals** (error + performance telemetry)
- a11y-first: semantic HTML, ARIA, keyboard nav, focus trapping, visible focus rings, reduced-motion.

## Run / build

```bash
cd apps/web
npm install
cp .env.example .env      # fill in VITE_SUPABASE_URL + VITE_SUPABASE_ANON_KEY (broker optional)

npm run dev               # local dev server (http://localhost:5173)
npm run typecheck         # tsc --noEmit
npm run lint              # eslint (+ jsx-a11y)
npm run test              # vitest unit tests (ported logic)
npm run build             # tsc -b && vite build  → dist/
npm run preview           # preview the production build
```

## Environment (`.env`, gitignored)

| Var | Required | Purpose |
|---|---|---|
| `VITE_SUPABASE_URL` | yes | Supabase project URL (the project the backend syncs into) |
| `VITE_SUPABASE_ANON_KEY` | yes | anon/publishable key — safe on clients; RLS gates access |
| `VITE_BROKER_URL` | no | auth broker base URL; empty ⇒ only Email-code login is shown |
| `VITE_SENTRY_DSN` | no | Sentry browser DSN; empty ⇒ Sentry init skipped |

## Structure

```
apps/web/
  index.html                 OG/Twitter/canonical meta (N1) + passkey.js
  public/                    manifest, icons (copied from the Flutter app), passkey.js bridge
  src/
    main.tsx                 entry: Sentry, web-vitals, React Query, Theme/Toast providers, router
    router.tsx               route map (auth guard) — mirrors the go_router contract
    lib/                     config, supabase, member model + select, broker, passkey, admin,
                             disclaimer copy, error reporter
    logic/                   framework-free ported logic (unit-tested):
                               dates.ts        parseMemberDate / fmtLong / monthsDaysAgo / staleness
                               milestones.ts   Golden Hour milestones + eligibility + OrgBucket
                               kpis.ts         baptismsByMonth (#1/#2) / metricData / lessons / units
    theme/                   CSS design system (light/dark via [data-theme]) + tokens
    hooks/                   useAuth, useTheme, useTier, useDashboard (the data layer + N3 poll)
    components/              Icon, ui primitives, Modal/Toast/Menu, GoldenHourChips, Skeletons,
                             dashboard building blocks, drill/sync/report sheets, EmptyState, TrendLine
    pages/                   LoginPage, DashboardShell, tabs/*, PersonDetailPage, SettingsPage,
                             InvitePage, AdminPage, ConfigError
    test/                    vitest tests mirroring the Flutter tests
```

## Parity notes

- **Single source of truth** is preserved per concept (mirrored from the Flutter files):
  the member select (`lib/member.ts` ← `dashboard_page.dart _columns`), Golden Hour milestones /
  eligibility / OrgBucket (`logic/milestones.ts` ← `golden_hour.dart`), the KPI math
  (`logic/kpis.ts` ← `dashboard_common.dart`), and the disclaimer / rules copy
  (`lib/disclaimer.ts` ← `disclaimer.dart`).
- **3-mode login** (Church + MFA, Email code with broker-relay fallback, passkey), the **N2**
  no-access block, **#6** consent wording, and broker **warm-up (N5)** all mirror `login_page.dart`.
- **Syncing banner** auto-polls `sync_state` every ~5s and self-clears (**N3**); investigators show
  only in Baptisms / Golden-Hour "Being Taught" (**N7**); friends **count** (#3); baptisms-by-month
  + best month (#1/#2); Rules & definitions in Settings (#4).
