-- 0044: calling gate for the login fast paths (the "a member with NO calling could sign in" report).
--
-- WHY: the login eval's fast paths (zero-LCR lane + credential-on-file path, ADR-009) returned
-- authorized:true for ANY valid Church account in an already-enrolled stake — the N2 calling check
-- only ran on the slow full-eval path. RLS still hid all data (no user_roles row), but any stake
-- member could mint a session and land in an empty app recorded as "allowed".
--
-- FIX (broker, enroll.py): LCR's /api/user-context — already fetched before the fast path
-- authorizes — positively shows a no-calling member (activePosition/positions/childUnits all
-- null; HAR-verified 2026-06-10). The broker now blocks on that signal and caches the outcome
-- here so the zero-LCR repeat-login lane can't authorize past the gate.
--
-- NULL (pre-migration rows) is NOT trusted: the zero-LCR lane requires has_calling IS TRUE; NULL
-- and FALSE fall through to the LCR-backed path, which re-runs the gate and refreshes this flag.

alter table church_identities add column if not exists has_calling boolean;
comment on column church_identities.has_calling is
  'Last login-eval gate outcome: true = user-context showed a calling (zero-LCR lane may authorize); false = positively no calling (blocked); null = not yet evaluated (must take the LCR-backed path).';

comment on column login_audit.phase is
  'fast-lane (cached identity, zero LCR) | fast (credential on file) | gate (blocked: user-context shows no calling) | full (access scrape)';

-- PostgREST must see the new column immediately (otherwise the broker's writes 400 until reload).
notify pgrst, 'reload schema';
