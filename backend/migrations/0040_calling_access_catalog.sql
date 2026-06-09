-- Calling → access-level catalog (feedback #1): which LCR callings can pull which covenant-path
-- data, persisted so the platform KNOWS each calling's level without a live probe. Seeded by code
-- (backend/access_levels.BASELINE) and DYNAMICALLY refreshed on every daily sync from the scraped
-- LCR access matrix — if the Church changes a calling's permissions, the next sync updates the row.
-- Drives "would this leader's credential be higher than the stored one?" messaging and the ops view.
-- Admin-only visibility (calling names are not PII, but the matrix is operational detail).
-- Additive + idempotent.

create table if not exists calling_access_catalog (
    role_id       integer primary key,   -- LCR position-type id (stable; names get localized)
    calling_name  text,
    features      text[] not null default '{}',  -- granted covenant-path feature keys
    feature_count integer not null default 0,    -- granted DATA features (perspective ones excluded)
    level         text not null default 'none',  -- 'full' | 'most' | 'partial' | 'none' (access_levels.py)
    source        text not null default 'scrape',-- 'baseline' (hardcoded seed) | 'scrape' (LCR matrix)
    updated_at    timestamptz not null default now()
);

alter table calling_access_catalog enable row level security;
grant select on calling_access_catalog to anon, authenticated;
grant insert, update, select on calling_access_catalog to service_role;

drop policy if exists calling_access_catalog_select on calling_access_catalog;
create policy calling_access_catalog_select on calling_access_catalog for select using (is_admin());
