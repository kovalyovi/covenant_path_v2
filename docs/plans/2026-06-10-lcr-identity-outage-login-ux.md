# Plan: LCR-identity failures at login — resilience, root-cause audit, honest messaging

**Status: EXECUTED 2026-06-10** (Phases 0–3 + the addendum fixes below; Phase 4 deliberately
deferred). Live-verified against the still-degraded LCR: the leg now classifies
`lcr_5xx / auth/me 502`, retries within budget, and returns the honest outage message.

## Addendum (same day): the father's report — two more findings, both fixed

1. **"Password field is impossible to enter — cursor gets lost"**: `Modal.tsx`'s focus-trap
   effect depended on `[open, onClose]`; every caller passes an inline `onClose` arrow, so each
   keystroke re-ran the effect and refocused the dialog container (blurring the input). Affected
   EVERY dialog with an input (ReauthDialog password, AdminPage invite, notes…). Fixed by reading
   the latest `onClose` through a ref and depending only on `[open]`; regression test
   `apps/web/src/test/modal.test.tsx` (verified to FAIL against the old dep array).
2. **"He wasn't able to do sync for his stake — why?"**: his 13:09 UTC sign-in succeeded via the
   cached-identity lane (no LCR), but *authorize sync* (enroll=true) must mint a FRESH LCR session
   (it IS the credential being stored) — impossible during the outage; his `avkov` attempts at
   13:10/13:11 are the `lcr_identity_failed` rows. Also fixed the misleading client behavior:
   a consented enroll that stored nothing now says so (ReauthDialog keeps the dialog open with the
   server error; LoginPage alerts before navigating) instead of toasting
   "sync authorization completed". `BrokerResult` now carries `enroll.error` as `enrollError`.

**Execution deviation**: `enroll._user_context_with_establish` keeps its own single
establish-retry (its failures are err-toward-allow, never user-facing 503s); the shared
retry helper is used by the identity leg, where the user-facing failures were.

## The incident (investigated, root cause confirmed)

vzhdanov (no leadership calling, stake not onboarded) tried signing in twice
(11:56 and 12:26 UTC, request ids `951bb3b6` / `bc916921`) and both attempts failed with
`lcr_identity_failed` — "Your password was accepted, but LCR didn't answer when we asked who
you are…". He (and the user) expected an "insufficient permissions" outcome instead.

**Root cause — reproduced live at 13:03 UTC with a different account from a different IP:**

```
okta password leg: 1.4s OK
LCR SSO leg:       0.3s OK
/api/auth/me:      502 text/plain in 0.1s — 6/6 consecutive tries
/api/user-context: 503 application/octet-stream in 3.7s
```

- This was a genuine **LCR API outage**, not account-specific, not stake-related, **not a
  timeout** (instant 502s — increasing timeouts would not have helped).
- Outage window started between 04:48 UTC (last successful full-path login, av_kov, 18.4s)
  and ~10:29 UTC (the local rate-finder run crashed — plausibly the same outage).
- The "insufficient permissions" outcome he expected **requires LCR**: a first-time login's
  calling gate runs on `/api/user-context` (enroll.py `calling_gate_check`), which was also
  down. We could not have known who he was, let alone what calling he holds. Once LCR
  recovers, his retry will take the normal path: identity → user-context → calling gate →
  `authorized:false` → the client's no-access message. Nothing about non-onboarded stakes is
  broken per se.

**Real gaps found while investigating** (what this plan actually fixes):

1. `login_audit.error` stores the *friendly client message*, not the root cause — a 502, an
   SSO-landed-on-Okta, and a timeout are indistinguishable after the fact. `duration_ms` and
   `phase` are NULL on these rows (`_audit_okta_failure`, app.py:362).
2. No retry anywhere on the identity leg — a 2-second LCR blip fails a whole login.
3. Latent timeout-budget mismatch: server identity leg worst case = 60s (SSO) + 60s
   (`/api/auth/me`) = 120s, which exceeds the client's 95s per-attempt window (broker.ts)
   and 110s page budget (LoginPage.tsx) — the user would see a client timeout while the
   server still "succeeds".
4. One generic message for every identity failure mode; a hard LCR outage reads like
   "maybe our service is flaky".
5. (Known/accepted) First-time users cannot be evaluated during an LCR outage at all; only
   cached-identity repeat logins ride the zero-LCR lane.

## Execution plan

### Phase 0 — root-cause capture in the audit trail (small, do first)

Files: `backend/auth_broker/okta_flow.py`, `backend/auth_broker/app.py`.

- Add a small classifier next to `IdentityError`, e.g.
  `_classify_lcr_failure(exc) -> (kind, root_cause)` with kinds:
  `lcr_5xx` (LoginError text contains "failed: 5"), `sso_rejected` ("landed back on Okta"),
  `timeout` (requests.Timeout in the `__cause__` chain), `network` (ConnectionError), `other`.
- `IdentityError` carries `kind` and `root_cause` attributes (message stays the friendly text).
- `_audit_okta_failure` gains `duration_ms` + writes `error = root_cause` (e.g.
  `"auth/me 502 text/plain"` — pull from the underlying `LoginError` / `exc.__cause__`),
  and `phase = "identity:" + kind`. The HTTP 503 `detail` keeps the friendly message.
- `dump_debug("broker_identity_error", ...)` already exists; add `kind`/`root_cause` fields.

### Phase 1 — retry + timeout budget on the identity leg

Files: `lcr_client/okta_login.py`, `backend/auth_broker/okta_flow.py`,
`backend/auth_broker/enroll.py`.

- New shared helper in `okta_login.py`:
  `establish_and_verify(session, *, attempts=3, backoff_s=2.0, leg_timeout=45) -> dict`
  — runs `_establish_lcr_session` + `_verify` with per-request timeout `leg_timeout`,
  retrying ONLY transient kinds (5xx / timeout / connection error; retry
  `sso_rejected` exactly once — could be a race). Hard total budget ≤ ~80s so the worst case
  fits inside the client's 95s window with headroom (today's instant-502 outage costs only
  ~3 extra seconds of retries).
- `okta_flow._identity` uses it; `enroll._user_context_with_establish`'s
  establish-then-retry path reuses the same helper for its establish leg (one retry policy,
  one place).
- Drop the raw 60s timeouts in `_establish_lcr_session`/`_verify` to the parametrized 45s
  (measured: 13s good day, 90s+ under extreme load — the fast lanes exist precisely so
  repeat logins never pay this; for first logins two 45s tries beat one 60s try).

### Phase 2 — honest, mode-specific user messages (server-side only → all 3 surfaces inherit)

Files: `backend/auth_broker/okta_flow.py` (message construction only).

- `lcr_5xx` (fast 5xx, the vzhdanov case):
  "Your password was accepted, but the Church's LCR system appears to be having an outage
  right now (it answered with an error, not silence). This isn't about your account or
  permissions — please try again later."
- `timeout` / `network`: keep today's "slow or briefly down — try again in a minute".
- `sso_rejected`: "Your Church sign-in worked, but LCR didn't accept the session. Try
  signing in once at lcr.churchofjesuschrist.org, then retry here." (Not yet observed in
  the wild; classification exists so we'll SEE it in login_audit if it ever happens.)
- Messages stay in the broker `detail` — web/iOS/Android already render `detail` verbatim,
  so **zero client-side changes**; just confirm in PARITY review that both native apps
  surface the 503 detail string (they do for current IdentityError text).

### Phase 3 — outage awareness (cheap, in-process circuit hint)

Files: `backend/auth_broker/okta_flow.py` (module-level state), optionally `app.py /health`.

- Track consecutive identity failures in-process: `{first_failed_at, count, distinct_users}`.
  When ≥2 distinct usernames have failed within 15 min, append to the message:
  "LCR has been unresponsive since HH:MM UTC." and expose `lcr: "degraded"` in `/health`.
  Reset on any success. No migration, no new table (Render = single instance; best-effort).
- Optional follow-up: probe-lcr.yml already logs in via `okta_login.login()` — its existing
  diagnostics row already fails loudly when auth/me is down; no change required.

### Phase 4 — OPTIONAL / separate decision: Okta-side identity fallback

Goal: during an LCR outage, *known* people still get in; *unknown* people get a correctly
attributed audit row (today the row has just the bare username, no email/name).

- On `IdentityError`, attempt `_exchange_code` (already implemented; works for enrolls) and
  decode the **id_token claims** (email / name / preferred_username) — Okta was healthy
  throughout this outage.
- With Okta-claimed email: (a) audit rows get real identity; (b) if `church_identities` or
  `user_roles` already knows this email (provisioned leader / prior login), err-toward-allow
  and mint the session (worst case: empty app; RLS is the data gate); (c) unknown emails
  (the vzhdanov case) still get the outage message — the calling gate must stay
  LCR-positive (0044 invariant: only a positive user-context read may set has_calling).
- Precondition: one-off probe to verify the Church Okta id_token actually carries an email
  claim for this client id. Do NOT start this phase until 0–3 are shipped and verified.

## Testing (per CLAUDE.md rule 4)

- `backend/test_broker.py`: new cases — classifier kinds (502 body, timeout, SSO redirect),
  retry-on-5xx then success, no-retry-past-budget, audit row carries root cause +
  duration_ms + phase. Mock at the `requests.Session` level like existing tests.
- Full backend suite: `python tools/test_suite.py`, `python -m backend.test_rls`,
  `test_power_users`, `test_admins`, `test_broker`, `test_login_audit`, `test_reconcile`,
  `test_calling_overrides`.
- Web: untouched (server-driven messages) — if anything web is touched anyway:
  `npm run typecheck` · `npm run test` · `npm run build`.
- Native: no edits needed; flag parity check (detail rendering on 503) in the commit message.
- Post-deploy manual: re-run the reproduction probe (Okta → SSO → auth/me, script in the
  2026-06-10 session); confirm a fresh `lcr_identity_failed` row (if LCR still down) now
  shows the root cause + duration; once LCR recovers, have vzhdanov retry — expected:
  calling gate → `authorized:false` → the client's no-access message.

## Rollout

- One focused commit straight to `main` (workflow rule 7), broker auto-deploys to Render.
- No migrations, no env changes. Kill switches unaffected (`CP_DISABLE_CALLING_GATE`
  untouched).
- Verify in `login_audit` by request id after the next real-world failure/retry.

## Explicitly NOT doing

- Increasing timeouts as the headline fix — the incident was instant 502s; timeouts never
  fired. (We *tighten* them to fit the client budget instead.)
- Client-side error mapping (would need 3-surface lockstep for zero benefit — messages are
  server-authored).
- Blocking "stake not onboarded" earlier: onboarding state is irrelevant until identity +
  calling are known, and both need LCR.
