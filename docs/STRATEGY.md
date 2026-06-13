# Strategy — backend free-tier resilience (#67 §4)

> **Most of this doc is obsolete (Flutter app deleted 2026-06-13).** The original strategy
> covered four questions for the old single Flutter codebase — graph library (fl_chart), an
> in-house design-token/component layer, splitting the 2,270-line `dashboard_page.dart`, and
> "ship native via the existing Flutter codebase." All of that is moot: the web app is now
> **React (`apps/web`)** and the mobile apps are **native Swift (`native/ios`) + Kotlin
> (`native/android`)** — see `CLAUDE.md` ("Making a change uniformly across views") and
> `native/PARITY.md`. UI structure now lives per-surface (`apps/web/src/`,
> `native/ios/Sources/`, `native/android/.../`), so the Flutter-internal UI/native strategy was
> dropped. Only the **backend free-tier** section below still applies — the failover runbook
> (`docs/RUNBOOK_FAILOVER.md`) points to it.

---

## Backends (free-tier resilience)

**Current stack & free-tier exposure**

| Service | Role | Free-tier limit / risk | Swap difficulty |
|---|---|---|---|
| **Supabase** | Postgres + Auth + RLS (system of record, ADR-001) | 500 MB DB, 2 projects, **pauses after ~1 wk inactivity** (daily sync keeps it warm) | **High** — RLS + Auth + REST are deeply used |
| **Render** | auth broker (FastAPI) | sleeps after 15 min idle (mitigated: retry + keep-warm) | **Low** — any container host (Fly/Railway) |
| **Cloudflare Pages** | web app hosting | generous; 500 builds/mo | **Low** — any static host |
| **GitHub Actions** | daily sync + deploys | 2,000 min/mo private (public = free) | **Low** — any cron/CI |
| **Resend** | email | 3,000/mo, 100/day | **Low** — mailer is provider-agnostic (SMTP fallback already) |
| **Google Sheets** | coarse export | free | **Low** — optional already |

**Reality check.** Only **Supabase** is a hard dependency (RLS is the access model — ADR-001/0002).
Everything else is already swappable or has a documented fallback. The user's ask ("configure their
backends if we get close to losing free tiers") is mostly about **removing hard-coding**, not
migrating now.

**Options**
- **A — Config-ize what's already swappable (recommended, mostly done).** Broker URL, app URL,
  spreadsheet id, email transport, GitHub repo are env / build-time vars already (the web build
  reads `VITE_*` env at build time; see `docs/DEPLOYMENT.md`). Gap: a single documented "providers"
  matrix + a `docs/RUNBOOK_FAILOVER.md` (how to repoint each piece) — both now exist. Cheap.
- **B — Reduce the Supabase lock-in surface.** Keep RLS but ensure the schema + migrations are
  portable Postgres (they are — plain SQL), and the app talks to Supabase only through a thin data
  layer so a move to self-hosted Postgres + PostgREST/Supabase-OSS is a config change. Medium.
- **C — Self-host everything** (Supabase OSS / a VPS). Removes tier risk entirely but adds ops
  burden + cost. Only if we actually outgrow free tiers.

**Recommendation.** **A now, B opportunistically.** The failover runbook + a one-screen "providers"
table now exist (`docs/RUNBOOK_FAILOVER.md`); keep migrations vendor-neutral SQL (already true);
introduce a thin client data layer only when we touch those call sites anyway. Defer C until a real
limit bites (the daily sync already prevents the Supabase idle-pause, the main near-term risk).
