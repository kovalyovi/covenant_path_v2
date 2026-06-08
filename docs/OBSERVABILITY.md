# Observability & access-visibility logging

**Purpose:** answer two questions at any time —
1. **Under-visibility:** is someone *not* seeing data they *should*? (a leader logged in but sees an empty app)
2. **Over-visibility:** is someone seeing data they *shouldn't*? (wrong/extra role scope)

…plus normal health/error observability. This doc maps every log sink and what's covered. Pair with
[`ACCESS_MODEL.md`](ACCESS_MODEL.md) (who-can-see-what) and `LOGGING_SETUP.md` (Axiom setup).

---

## 1. Where logs go (sinks)

| Sink | What | Persistence | Who reads it | Source |
|---|---|---|---|---|
| **`login_audit`** table | One row per Church-login eval: email, stake, callings, `authorized`, `access_rank`, `can_pull_all`, **`role_scope`**, outcome | Supabase (admin-only RLS) | Admin console → **Recent logins** | `0033`/`0034`, `enroll.py` |
| **`access_audit`** table | Every role **grant/revoke** from provisioning: who, calling, role, scope, action | Supabase (admin-only RLS) | Admins (query/console) | `0034`, `roles.py` |
| **`sync_diagnostics`** table | Per-sync run stats, field coverage, request metrics, failed units | Supabase | Admin console → Diagnostics | `0013`, `daily_sync.py` |
| **Axiom** (structured) | PII-safe JSON events (IDs/counts/durations/status) across sync + broker; correlation-id per run | 30-day (free tier) | Axiom dashboard / in-app log views | `observability.py` |
| **Sentry** | Client crashes/errors (Flutter + native) | Sentry | Sentry dashboard | `error_reporter.dart`, `config.dart` |
| **`/log`** broker endpoint | Client-side errors/failed calls → forwarded to Axiom (PII-scrubbed, size-capped) | via Axiom | Axiom | `app.py` `client_log` |
| **stderr → Render** | Broker `logger.*` lines (login eval, errors) | ephemeral (Render log viewer) | Operator | `logging_setup.py` |
| **File logs** | `tools/output/logs/session_*.log` (sync runs) | local / CI artifact (14-day) | Operator | `logging_setup.py` |

> **PII policy (Axiom):** `observability.py` *drops* `name/email/birth_date/address/phone`. So names
> and emails live **only** in the admin-only audit **tables** (`login_audit`, `access_audit`), never
> in Axiom. That's deliberate — queryable identity for admins, no PII in third-party telemetry.

---

## 2. The two visibility questions — what covers them now

### Under-visibility ("can't see what they should")
- **Login blocked wrongly** → `login_audit.outcome='blocked'` **with the callings logged**, so a
  mis-classified leader (e.g. the stake-president false-block, fixed 2026-06-08) is visible.
- **Logged in but sees nothing** → `login_audit.role_scope='none'`: the sign-in succeeded but no
  `user_roles` row resolves for them (RLS returns zero rows). **This is the key new signal** — it
  catches the email-binding gap where a real leader's role row never got their email.
- **Lost access they should keep** → `access_audit action='revoked'` names exactly who/what/when.

### Over-visibility ("sees what they shouldn't")
- **Gained access** → `access_audit action='granted'` (who, calling, role, scope) — review for any
  grant that looks wrong.
- **Unexpected scope at login** → `login_audit.role_scope` naming a stake/role they shouldn't have.
- **The hard guarantee:** RLS is default-deny and stake/ward-scoped (see `ACCESS_MODEL.md` §2). A
  user with no role sees nothing; the audits make *role state changes* observable on top of that.

---

## 3. Gaps CLOSED this session (2026-06-08)

- ✅ **Login gate no longer false-blocks** on an empty access probe (`enroll.py`) — and logs the
  runner's callings on the no-access path.
- ✅ **`login_audit`** — persistent who/stake/callings/access/outcome (was: only an ephemeral
  `authorized/stored` stderr line).
- ✅ **`login_audit.role_scope`** — what each sign-in *actually resolves to* (under/over visibility).
- ✅ **`access_audit`** — per-person grant/revoke trail from `provision_roles` (was: only counts).
- ✅ Both audit tables are **admin-only (RLS)** and **tested** (`test_login_audit.py`).

---

## 4. Gaps REMAINING (honest — recommended follow-ups)

| Gap | Risk | Suggested fix |
|---|---|---|
| **Direct email-OTP / passkey logins partly audited** | Relay (broker) email logins now write `login_audit`; the *direct* browser→Supabase email-OTP + passkey paths aren't broker-visible | A Supabase Auth hook would capture every auth event; the relay path is covered |
| **Admin & power-user actions not in an audit table** | `invite_admin` / `invite_power_user` / `revoke_*` only `logger.info` | Route them into `access_audit` with `source='power_user'/'manual'` (table already has the column) |
| **No alerting on sync failure** | A stake silently stops syncing; logged but nobody's paged | Add a digest/notify when a stake's `last_synced_at` goes stale or `failed_units` is non-empty |
| **Per-query data access not logged** | Can't replay *exactly* which rows a user fetched | Intentional — RLS guarantees scope; row-level read logging would be heavy/noisy. Rely on `role_scope` instead |
| **Native/React admin "Recent logins" view** | Audit visible only in Flutter console today | Port the panel to `apps/web` + native admin screens |
| **Axiom retention is 30 days (free tier)** | Long-term trend loss | The Supabase audit tables are the durable record; Axiom is for live ops |

---

*Update this doc when you add a log sink or change what's audited. Tables: `login_audit` (`0033`/`0034`),
`access_audit` (`0034`), `sync_diagnostics` (`0013`).*
