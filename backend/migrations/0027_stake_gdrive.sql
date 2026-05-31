-- M7: per-stake Google Drive (OAuth). A stake's leader connects their Google account; the stake's
-- spreadsheet is created + maintained in THEIR Drive (their storage), so the platform never owns it.
-- gdrive_token = the envelope-encrypted refresh token (CP_TOKEN_KEY, same vault as stake_credentials).
-- Takes precedence over the service-account/master paths in _resolve_stake_sheet.
alter table stakes add column if not exists gdrive_token text;       -- encrypted refresh token (or null)
alter table stakes add column if not exists gdrive_email text;       -- the connected Google account
alter table stakes add column if not exists gdrive_file_id text;     -- the spreadsheet id in that Drive
alter table stakes add column if not exists gdrive_connected_at timestamptz;
