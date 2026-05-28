-- Signed URL for each member's avatar (stored in a PRIVATE Supabase Storage bucket by the
-- photo pipeline). We keep the signed URL on the member row so the app reads it under the
-- same members RLS that already gates the member — no separate Storage RLS needed, and the
-- URL is only ever visible to a viewer already allowed to see that member. photo_path
-- (added in 0009) holds the storage object path for idempotent re-upload. Additive.

alter table members add column if not exists photo_url text;
