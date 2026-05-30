# M7 — Per-stake Google OAuth Drive (design)

**Goal:** each stake fully **owns** its spreadsheet. A leader signs in with their own Google
account, grants Drive access, and we create + maintain the stake's sheet **in their Drive** — the
operator (platform owner) can't see or edit it. This is the chosen alternative to the single
platform service account (see [[project_per_stake_sheets]] and `docs/CUSTOM_API_KEYS.md`).

Status: **designed, not built.** It is security-sensitive (OAuth + encrypted refresh tokens) and
needs a Google Cloud OAuth client that only the project owner can create — so it ships only with
those credentials in hand and live-tested, never rushed.

## What the owner must create first (prerequisite)

1. **Google Cloud project → OAuth consent screen** (External, "Covenant Path"), scopes:
   `https://www.googleapis.com/auth/drive.file` (create/manage only files the app makes — minimal),
   plus `openid email`.
2. **OAuth 2.0 Client ID** (type: Web application). Authorized redirect URI =
   `https://covenant-path-broker.onrender.com/auth/google/callback` (+ `http://localhost:8787/...`
   for dev). Gives a **client ID + client secret**.
3. Enable the **Google Drive API** + **Google Sheets API** on that project.
4. Put on the broker (Render) + `.env`: `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`,
   `GOOGLE_OAUTH_REDIRECT`. (`.env.example` should document these when built.)

Until those exist the feature stays a **no-op** (the "Connect Google Drive" button is hidden when
the client id is unset), exactly like the Axiom/Sentry pattern.

## Flow

```
Leader (app) ──"Connect Google Drive"──▶ broker /auth/google/start
   broker redirects to Google consent (state = signed JWT of stake_id + nonce, access_type=offline)
Google ──code──▶ broker /auth/google/callback
   broker exchanges code → { refresh_token, access_token }
   encrypt refresh_token with CP_TOKEN_KEY (reuse backend/credentials vault) → store on the stake
Daily sync (that stake) ─▶ refresh access_token from the stored refresh_token
   create the sheet in the leader's Drive (drive.file) if none stored; else update it
   share read-only with the stake's leadership emails (Drive permissions.create)
```

## Pieces to build

- **Migration 00NN:** `stakes.gdrive_token bytea` (encrypted refresh token), `stakes.gdrive_email
  text`, `stakes.gdrive_file_id text`. (Keep `spreadsheet_id` for the service-account path; gdrive_*
  takes precedence when present.)
- **`backend/auth_broker/google_oauth.py`:** `start_url(stake_id)` (signed state), `exchange(code,
  state)` → store encrypted refresh token via the existing `backend/credentials` envelope vault
  (CP_TOKEN_KEY), `access_token_for(stake)` (refresh on demand).
- **Broker routes:** `GET /auth/google/start?stake=…` (auth-gated to a provider of that stake) →
  302 to Google; `GET /auth/google/callback` → store + close-the-popup HTML.
- **`sheets_sync/oauth_drive.py`:** create/share/write a sheet with a user access token (Sheets +
  Drive REST). `_resolve_stake_sheet` (scripts/daily_sync.py) prefers the gdrive path when the stake
  has a token, else the per-stake service-account sheet, else (operator only) the master.
- **App:** a "Connect Google Drive" tile in Settings / Sync settings (only when the broker reports
  the OAuth client is configured); shows connected account + a disconnect.

## Security notes (must hold)

- Store **only the refresh token, encrypted** (CP_TOKEN_KEY); never log tokens. Same vault + rules
  as the LCR delegated credentials ([[project_delegated_onboarding]]).
- `drive.file` scope only — the app can touch **only the files it creates**, not the leader's whole
  Drive.
- `state` is a signed, short-TTL JWT bound to the stake + a nonce → no CSRF / stake-swap.
- The callback must verify the signed-in caller is a **provider for that stake** before binding.
- Disconnect = delete the stored token (and optionally the sheet).

## Tests to add

- `google_oauth` state sign/verify round-trip + tamper rejection (offline).
- token encrypt/decrypt via the vault (reuse the existing token-store test pattern).
- `_resolve_stake_sheet` precedence: gdrive → service-account → master(operator-only).
