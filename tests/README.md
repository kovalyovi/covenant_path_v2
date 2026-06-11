# Covenant Path test harness

Everything in `tests/` is **fictional** (public repo): Testvale North Stake `999001`,
wards `999101`/`999102`, example.org people ("Avery Example"). No real member data, unit
numbers, credentials or Church endpoints appear anywhere here.

Install once: `pip install -r requirements.txt -r requirements-dev.txt`

## Lane 1 — mock e2e (no network, no secrets, CI-safe)

```
python -m pytest tests/e2e -q
```

What it boots (session-scoped, free ports):

| piece | what |
|---|---|
| `tests/mock_lcr` | mock **Okta/identity** host (full IDX dance: interact → introspect → identify → select/challenge → answer → interaction-code) + mock **LCR** host (`/api/auth/login` SSO redirect chain, `/api/auth/me`, `/api/user-context`, `/other/access-table` with `__NEXT_DATA__`). Two ports, one shared state — `establish_lcr_session` needs distinct netlocs. |
| `tests/supabase_stub` | in-memory PostgREST + GoTrue stub (tables, embeds — to-one returns an **object** —, `Prefer: count=exact`, upserts, `rpc/enroll_stake_credential` with the exact 0041 WHERE arms, `generate_link`/`verify`/`user`). |
| the **real broker** | `uvicorn backend.auth_broker.app:app` subprocess with `CP_TEST_MODE=1`, `CP_TEST_LCR_BASE`/`CP_TEST_IDENTITY_BASE` → mocks, `SUPABASE_URL` → stub, `LOGIN_EVAL_BUDGET_SECONDS=30`, throwaway `CP_TOKEN_KEY`, **no** `GITHUB_TOKEN`/`RESEND_API_KEY`. Its log: `tools/output/e2e_broker.log` (gitignored). |

Personas (mock Okta usernames / passwords; MFA code is always `123456`):

| username | password | shape |
|---|---|---|
| `president.complete` | `pw-president` | no MFA; stake-president context; access matrix → `can_pull_all` |
| `wardleader.partial` | `pw-ward` | bishop; partial access with who-to-ask |
| `member.nocalling` | `pw-member` | valid login, user-context shows **no calling** (gate shape) |
| `member.mfa` | `pw-mfa` | MFA shape A (email + SMS factor menu) |
| `member.mfab` | `pw-mfab` | MFA shape B (straight code challenge) |
| `user.locked` | (any) | always "Your account is locked" |
| anything else | (any) | IDX 401 `Authentication failed` |

Control planes (used by the tests; handy manually too):

- mocks: `POST /__test/control {"scenario": "healthy"|"lcr_5xx"|"identity_timeout"|"sso_reject"}`,
  `GET /__test/state` (scenario + per-path hit counters), `POST /__test/reset`
- stub: `POST /__test/seed {"stakes": [...], ...}` (replaces listed tables),
  `GET /__test/rows/{table}`, `POST /__test/reset`, `GET /__test/state`

Run the mocks standalone (manual poking):

```
python -m tests.mock_lcr          # identity :8901 + LCR :8902
python -m tests.supabase_stub     # supabase stub :8903
```

## Lane 2 — RLS matrix against a REAL test Supabase project (Phase B)

Needs a **dedicated test project** (never prod). One-time setup:

```
SUPABASE_DB_URL=<TEST project db url> python -m backend.apply     # apply migrations
set CP_TEST_SUPABASE_URL=<test project url>
set CP_TEST_SUPABASE_SERVICE_ROLE_KEY=<test service key>
set CP_TEST_SUPABASE_ANON_KEY=<test anon key>      # optional: enables the anon assertions
python -m tests.seed                               # fictional fixtures; idempotent
```

`tests/seed.py` HARD-refuses to run when the env vars are missing **or** when
`CP_TEST_SUPABASE_URL == SUPABASE_URL`. Then:

```
python -m pytest tests/test_rls_matrix.py -q
```

The matrix test skips cleanly when the env isn't set, so the mock lane stays green in CI
without any Supabase project.

## Lint

```
python -m ruff check --select F821 tests
```
