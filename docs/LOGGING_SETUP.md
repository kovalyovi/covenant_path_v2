# Logging & observability setup (Axiom + optional Sentry)

The platform ships **structured JSON logs** from the sync layer, the broker, and the React web client
to **Axiom** (free tier). Everything **no-ops safely until you add the tokens** — nothing breaks if
this is never configured. **No PII is ever sent** — only IDs, `correlation_id`, counts, durations,
status, and truncated error messages (member names/birthdates/addresses are filtered, see
`backend/observability.py` `_PII_KEYS` + the broker `/log` allow-list).

## What's already wired (no setup needed to read this)
- `backend/observability.py` — the JSON event shipper (`event()` / `span()` / `flush()`), batched,
  best-effort, no-op without `AXIOM_TOKEN`.
- **Sync layer** — each per-stake job emits `sync.stake.start/finish/error` with a `correlation_id`,
  stake unit, and duration (`scripts/daily_sync.py:run_one_stake`).
- **Broker** — `POST /log` ingests client errors and forwards them to Axiom.
- **Web app** — `apps/web/src/lib/errorReporter.ts` POSTs uncaught errors / failed calls to the
  broker `/log`; `@sentry/react` (`apps/web/src/main.tsx`) adds an `ErrorBoundary` + crash reporting
  when `VITE_SENTRY_DSN` is set (see §2).

## 1. Axiom (structured logs) — ~5 minutes
1. Sign up at **https://app.axiom.co** (free: ~500 GB/mo ingest, 30-day retention).
2. **Create a dataset** named `covenant-path` (Settings → Datasets → New). If you pick another name,
   set `AXIOM_DATASET` to match.
3. **Create an API token** (Settings → API tokens → New) with **ingest** permission on that dataset.
   Copy it.
4. Add the token where logs originate:
   - **GitHub Actions** (the sync): repo → Settings → Secrets and variables → Actions → new secrets
     `AXIOM_TOKEN` and (if non-default) `AXIOM_DATASET`. Add them to the `env:` of `daily-sync.yml`'s
     jobs (mirror how `CP_TOKEN_KEY` is passed).
   - **Render** (the broker — for client error logs): broker service → Environment → add `AXIOM_TOKEN`
     (+ `AXIOM_DATASET`). Save → redeploy.
5. Verify: trigger a sync (Actions → Daily covenant-path sync → Run), then in Axiom open the
   `covenant-path` dataset — you should see `sync.stake.*` events. Query examples:
   - failing stakes: `event == "sync.stake.error"`
   - slow stakes: `sync.stake.finish | sort by duration_ms desc`
   - client errors: `event == "client.error"`

## 2. Sentry (web crash grouping) — already wired, just add the DSN
The broker→Axiom path already captures client errors; Sentry adds nicer crash grouping/alerting for
the React web app. It is **already integrated** (`@sentry/react` in `apps/web/src/main.tsx` —
`Sentry.init` + an `ErrorBoundary`), gated on the DSN, so it's a no-op until you set one:
1. Sign up at **https://sentry.io** (free dev tier), create a **React** project, copy the **DSN**.
2. Set the `SENTRY_DSN` GitHub secret — `deploy-web.yml` passes it to the build as `VITE_SENTRY_DSN`
   (`apps/web/src/lib/config.ts` reads it). For a local build, set `VITE_SENTRY_DSN` in the env.
3. That's it — the next deploy initializes Sentry. (The native iOS/Android apps don't ship a Sentry
   SDK; their uncaught-error reporting, if needed, would go through the broker `/log` path.)

## In-app views (next)
The OPS/Diagnostics console will read Axiom's query API to show logs + sync analytics in-app
(filter by stake/unit/level/correlation_id/window) with a "copy full context for Claude" action.
Until then, use the Axiom web UI directly with the queries above.

## Cost / retention
Free tiers cover current scale comfortably. Axiom auto-expires at 30 days. If you outgrow it, the
same `observability.event()` shape can point at any HTTP log sink (Better Stack, Grafana Loki) by
changing `AXIOM_URL` — no call-site changes.
