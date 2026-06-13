# M7 — Per-stake Google Drive ownership (OAuth)

**Status: SHIPPED.** Each enrolled stake can own its own spreadsheet in its leader's Google Drive.
This doc records what was built and where it lives (was: "designed, not yet built").

## Why

The platform's Google **service account has zero Drive storage** — it can call the Drive API but a
file it "creates" has no owner with quota. The fix: **each stake owns its own spreadsheet** in
*their* Drive, shareable with *their* leaders and revocable independently. The operator's own stake
still uses the master `SPREADSHEET_ID`.

## The approach (OAuth, per-stake)

A stake's sync provider connects their Google account once (OAuth, `drive.file` scope). We store an
envelope-encrypted refresh token on the stake and use it each sync to create + maintain that stake's
spreadsheet **in their Drive**; the OAuth identity owns the file, and the service account is shared
in as Editor so the existing `SheetsSync` writes the data unchanged. The platform never owns the file.

## What was built (where each piece lives)

1. **Google OAuth client** — `backend/auth_broker/google_oauth.py` (`drive.file` + `openid email`;
   HMAC-signed, stake-bound, short-TTL `state`; `start_url`, `exchange_code`, `refresh_access_token`,
   envelope `encrypt_refresh` / `decrypt_refresh`, `access_token_for`).
2. **Broker routes** — `backend/auth_broker/app.py`: `GET /auth/google/status`, `POST
   /auth/google/start`, `GET /auth/google/callback`, `POST /auth/google/disconnect` (all
   provider-gated via `admin.provider_stake_id`).
3. **Token store** — migrations `0027_stake_gdrive.sql` + `0028_stake_gdrive_grant.sql`:
   `stakes.gdrive_token` (envelope-encrypted), `gdrive_email`, `gdrive_connected_at`,
   `gdrive_file_id`. Read/write helpers in `backend/auth_broker/admin.py`
   (`gdrive_status_for`, `store_gdrive_token`, `disconnect_gdrive`).
4. **Sheet provisioning** — `sheets_sync/oauth_drive.py` (`ensure_sheet`: create-on-first-use in the
   leader's Drive, write headers, share Editor→service account + reader→leadership; idempotent).
5. **Web UI** — `GoogleDriveSection` in `apps/web/src/components/SyncSettingsSheet.tsx` (Sync
   settings): provider-only "Connect Google Drive", shows the connected email + the sheet link +
   last-refresh, and a Disconnect; self-gates (hidden) when the broker has no OAuth configured.
   Mirrored on the native Sync-settings screens (`native/ios`, `native/android`).
6. **Daily-sync wiring** — `scripts/daily_sync.py` `_resolve_stake_sheet`: if the stake has a
   `gdrive_token`, mint an access token (`google_oauth.access_token_for`) and use / `ensure_sheet`
   the per-stake file; else fall back (operator's own stake → master sheet; other stakes →
   service-account create if possible, else skip Sheets — Supabase still syncs).

## Operator prerequisite (one-time, to enable it)

The feature is a **no-op until** a Google Cloud OAuth client exists and its creds are on the broker:
`GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, `GOOGLE_OAUTH_REDIRECT`
(redirect = `<broker>/auth/google/callback`), with the Drive + Sheets APIs enabled and the
`drive.file` + `openid email` scopes on the consent screen. Until set, "Connect Google Drive" stays
hidden (same pattern as the other optional integrations).

## Resolved open questions

- **Token refresh / failure** — each sync exchanges the stored refresh token for a fresh access
  token (`refresh_access_token`); on failure it raises "the leader must reconnect Drive" and the
  sync degrades (Supabase still updates). The Sync-settings section surfaces the connection state.
- **Stakes that never connect Drive** — they simply don't get a per-stake sheet: the operator's own
  stake falls back to the master `SPREADSHEET_ID`; other stakes skip Sheets entirely (data still
  lands in Supabase, which is what the app reads). No stake is blocked on connecting Drive.

## Possible future polish (not blocking)

- Proactive in-app "reconnect Drive" nudge when a stored refresh token goes stale (today the failure
  is logged + the section shows disconnected on next load).
- Optionally let a non-provider leader connect Drive (today only the credential provider can).
- Sharing-by-calling precision: today the reader share list = the stake's `user_roles` emails +
  the credential `principal_email`; a calling allowlist could narrow it further.
