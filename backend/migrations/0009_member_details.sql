-- Rich one-work record for the LCR-style member detail view. The daily sync already
-- fetches /api/report/one-work/details/{id} (198 fields) but only kept ~13 scalars;
-- `details` now stores the progress-only subtree (sacrament attendance, friends,
-- lessons/principles, ministering names, temple/self-reliance commitments) so the app
-- can render the full layout. Contact PII (phone/email/social) is deliberately NOT kept.
-- `photo_path` is a slot for a later avatar pipeline (downsized image in Storage).
-- Additive + idempotent.

alter table members add column if not exists details    jsonb;
alter table members add column if not exists photo_path text;
