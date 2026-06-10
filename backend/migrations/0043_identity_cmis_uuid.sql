-- 0043: carry the LCR person UUID (auth/me churchCMISUUID) on the broker's identity cache.
--
-- WHY: calling-provisioned user_roles rows are keyed by lcr_person_uuid, but no login could
-- ever match them — RLS matches by auth_id (= auth.uid(), never the LCR uuid) or by verified
-- email (NULL on every calling row since the member-list enrichment endpoint died). Verified
-- live: /api/auth/me churchCMISUUID IS the same person uuid the org-callings endpoint reports,
-- so a Church login can stamp its verified email onto that person's role rows (the binding
-- lives in auth_broker/enroll.py). This column persists the uuid so cached (zero-LCR)
-- fast-lane logins can re-bind without ever touching LCR.
alter table church_identities add column if not exists cmis_uuid text;

-- The broker's binding PATCH goes through PostgREST as service_role, which had no UPDATE on
-- user_roles (sync writes connect as postgres directly) — without this the bind 42501s.
grant select, update on user_roles to service_role;

-- PostgREST must pick up the new column (0042 lesson: without the reload, REST writes that
-- include it 400 on "column not found" / silently fail).
notify pgrst, 'reload schema';
