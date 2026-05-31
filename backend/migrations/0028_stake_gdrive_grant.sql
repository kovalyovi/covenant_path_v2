-- The broker (service_role via PostgREST) writes the M7 Google Drive connection, but service_role
-- only had SELECT on stakes. Grant UPDATE on ONLY the four gdrive columns — the broker has no
-- business updating anything else on the row (the sync does that as the postgres role).
grant update (gdrive_token, gdrive_email, gdrive_file_id, gdrive_connected_at)
  on public.stakes to service_role;
