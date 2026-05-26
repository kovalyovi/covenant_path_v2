# Backend (Supabase / Postgres)

System of record for covenant-path data across **many stakes**, with access control
enforced by Postgres **Row-Level Security** (see `docs/DECISIONS.md` ADR-001).

## The access model (the whole point)

| Calling | `user_roles` row | Sees |
|---|---|---|
| Stake leader | `stake_id=X, unit_id=NULL, role=stake_leader` | **every member in stake X** |
| Ward leader  | `stake_id=X, unit_id=U, role=ward_leader`    | **only members in unit U** |

RLS applies to the Supabase API roles (`anon`/`authenticated`) using the viewer's JWT
(`auth.uid()`). The **scraper writes via the `postgres` role** (the `SUPABASE_DB_URL`
connection), which bypasses RLS — so syncing is unrestricted while app reads stay scoped.

## Tables (`migrations/0001_schema.sql`)

`stakes` → `units` → `members` (each member tagged `stake_id` + `unit_id`).
`app_users` links a Supabase auth user to an email; `user_roles` grants access
(unit_id NULL = whole stake). `members.updated_at` is trigger-maintained and is the
durable **incremental** signal in the cloud (skip members synced within the window).

## Setup

1. Put the DB connection string in `.env` (Supabase → Settings → Database → URI):
   ```
   SUPABASE_DB_URL="postgresql://postgres:<password>@db.<ref>.supabase.co:5432/postgres"
   SUPABASE_URL="https://<ref>.supabase.co"
   SUPABASE_ANON_KEY="sb_publishable_..."
   ```
2. Apply schema + RLS:  `python -m backend.apply`
3. Verify RLS works:    `python -m backend.test_rls`   *(seeds a throwaway stake, checks
   stake-leader sees 2 / ward-leader sees 1 / anon sees 0, then rolls back)*
4. Sync data:           `python -m backend.sync`        *(upserts `output/covenant_path_stake.json`)*
   or `python -m backend.sync --scrape --with-profile`

## How roles get provisioned (onboarding)

A stake's leadership is already known from LCR's leadership directory
(`lcr_client/leadership.py`). On onboarding we map: Stake President/clerk →
`stake_leader`; Bishop/ward clerk → `ward_leader` for their unit. Viewers log in with
Supabase Auth (email/Google); their `auth.uid()` is matched to a `user_roles` row.
(Onboarding automation is the next build; the schema + RLS are ready for it.)

## Notes / drawbacks

- The `postgres` role bypasses RLS by design (scraper writes). Do **not** expose
  `SUPABASE_DB_URL` to clients; only the anon/publishable key + a user JWT reach the API.
- Google Sheets cannot enforce ward-vs-stake within one file — that's why fine-grained
  access lives here, with Sheets as a coarse per-stake export.
