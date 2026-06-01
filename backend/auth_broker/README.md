# Church-login auth broker

"Sign in with your Church account" for **web + native**. A browser can't call the Church's
Okta directly (CORS); this small server can. It authenticates server-side (reusing
`lcr_client/okta_login`, MFA-aware), then mints a Supabase session the app verifies.

```
app (web/native)  ──username+password──▶  broker /auth/password
                                              │ okta_flow (IDX, MFA-aware)
                                              ▼
                                          identity (email) ──▶ Supabase Admin generate_link
                                              ▼
app  ◀── { email, otp } ── broker          (verifyOtp → RLS-scoped Supabase session)
```

## Endpoints
- `POST /auth/password` `{username,password}` → `{status:"ok", session:{email,otp}}` **or**
  `{status:"mfa_required", login_id, factors:[{id,label,method}]}`
- `POST /auth/mfa/select` `{login_id, factor_id}` → sends the code
- `POST /auth/mfa/verify` `{login_id, code}` → `{status:"ok", session:{email,otp}}`
- `POST /auth/session` `{cookies:[...]}` → native WebView path (app captured the Okta session
  itself; password only ever touched Okta) → `{status:"ok", session:{email,otp}}`
- `POST /auth/email/start` · `POST /auth/email/verify` → email-OTP **relay** (sign in when the
  browser can't reach Supabase directly, e.g. some regions)
- `GET /enrollment/status` · `POST /revoke` → the signed-in leader's stake enrollment + revoke
- `GET /report` · `POST /report/email` → ad-hoc convert-integration report for the caller's scope
  (`user_roles` matched by bound `auth_id` **OR** verified email)
- `POST /feedback` → file a **sanitized** GitHub issue (caps length, strips control chars, defangs
  @mentions / #refs / auto-close keywords; never auto-merges) · `POST /contact` → email the owner
- `GET /auth/google/status` + `/auth/google/start` + `/auth/google/callback` → per-stake Drive OAuth
- `POST /webauthn/register/begin|complete` · `POST /webauthn/authenticate/begin|complete` → passkeys
- `GET /admin/*` → admin/ops console (health, freshness, GitHub Actions, enrolled-stakes), gated by
  `app_admins`
- `GET /health`

> **Enrollment binds a role.** Storing a stake credential also binds the enroller's verified email
> to a stake-wide `stake_leader` `user_roles` row (trigger `trg_bind_provider_stake_role`, migration
> 0029) so an email/Google login sees their stake even though `provision_roles` keys roles on the
> LCR person UUID and the UUID→email member-list endpoint is dead.

The app then calls `supabase.auth.verifyOtp(email, otp)` to get the session.

## Run locally
```bash
uvicorn backend.auth_broker.app:app --reload --port 8787
```

## Deploy (free tier: Render / Fly.io / Railway)
Containerize the repo, start command `uvicorn backend.auth_broker.app:app --host 0.0.0.0 --port $PORT`.
Env required:
- `SUPABASE_URL`, **`SUPABASE_SERVICE_ROLE_KEY`** (Settings → API → service_role — the one
  secret still needed; minting fails without it)
- `ALLOWED_ORIGINS` (e.g. `https://app.membercovenantpath.org`)

Point the Flutter app at it with `--dart-define=BROKER_URL=https://broker.membercovenantpath.org`.

## Security / logging
- Password transits the broker over HTTPS and is **never stored or logged** (IDX answer is
  `redact=True`). MFA codes + session OTPs are likewise never logged.
- Every request logs a short id + each IDX step for troubleshooting; failures `dump_debug`
  a redacted record under `tools/output/debug/`.
- The headless `lcr_client.okta_login.login()` used by the daily sync is untouched.
