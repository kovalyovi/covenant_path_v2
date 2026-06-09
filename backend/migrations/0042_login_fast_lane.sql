-- 0042: login fast lane + reliable keep-warm + login timing in SQL.
--
-- WHY (2026-06-09, the ">75s to sign in" report): a Church-account sign-in spent its time in two
-- places that have nothing to do with verifying the password:
--   (a) Render cold starts — the GitHub keep-warm cron ("*/5") is best-effort and actually fired
--       every 2-4 HOURS, so the free-tier broker slept ~15 min after each ping and nearly every
--       real login ate a ~50-75s wake;
--   (b) the LCR SSO + /api/auth/me identity fetch — measured 13s on a good day and 90s+ while LCR
--       is under load — re-deriving an email/name/unit we already learned on PRIOR logins.
--
-- 1) church_identities: broker-only cache of Church username -> verified identity. After Okta
--    verifies the password, a repeat login takes its identity from here and skips LCR entirely;
--    the login eval reuses the cached unit_number for its stored-credential check (also no LCR).
--    Rows are refreshed on every full login. Service-role only: RLS enabled, NO policies.
-- 2) login_audit.duration_ms / .phase: how long the login had been running when the audit row was
--    written and which lane it took — so "which logins were slow, and where" is one SQL query.
-- 3) pg_cron keep-warm: ping the broker /health every 4 minutes from Postgres (pg_net), which
--    fires on schedule — unlike GitHub cron. The GH workflow stays as a free backstop.

create table if not exists church_identities (
  username    text primary key,
  email       text not null,
  name        text,
  cmis_id     text,
  unit_number bigint,
  stake_name  text,
  updated_at  timestamptz not null default now()
);
comment on table church_identities is
  'Broker-only: Church username -> identity verified on a prior full login (lets repeat logins skip LCR). RLS on, no policies — service-role access only.';
alter table church_identities enable row level security;

alter table login_audit add column if not exists duration_ms integer;
alter table login_audit add column if not exists phase text;
comment on column login_audit.duration_ms is
  'ms from request start to this audit write (the response may have returned sooner when the eval was deferred to background)';
comment on column login_audit.phase is
  'fast-lane (cached identity, zero LCR) | fast (credential on file) | full (access scrape)';

-- Keep-warm via pg_cron + pg_net. Guarded so a database without these extensions (local dev)
-- only WARNS instead of failing the whole migration transaction.
do $$
begin
  begin
    create extension if not exists pg_cron;
  exception when others then
    raise warning 'pg_cron unavailable (%) — keep-broker-warm NOT scheduled', sqlerrm;
    return;
  end;
  begin
    create extension if not exists pg_net;
  exception when others then
    raise warning 'pg_net unavailable (%) — keep-broker-warm NOT scheduled', sqlerrm;
    return;
  end;
  if exists (select 1 from cron.job where jobname = 'keep-broker-warm') then
    perform cron.unschedule('keep-broker-warm');
  end if;
  -- NOTE: if the broker URL ever changes, update it here (plus repo var BROKER_URL and
  -- .github/workflows/keep-broker-warm.yml) and re-apply migrations.
  perform cron.schedule(
    'keep-broker-warm',
    '*/4 * * * *',
    $job$ select net.http_get(url := 'https://covenant-path-broker.onrender.com/health', timeout_milliseconds := 8000) $job$
  );
end $$;
