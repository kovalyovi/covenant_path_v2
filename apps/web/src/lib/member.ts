// The member shape the dashboard reads from Supabase. Mirrors `_columns` in
// apps/viewer/lib/dashboard_page.dart — the single source for the Supabase select. Fields are
// loosely typed (Supabase returns JSON) and accessed via helpers; `details` is the rich one-work
// subtree used by the person-detail page.

/** Exact column list selected from `members` (mirrors the Flutter `_columns`). */
export const MEMBER_COLUMNS =
  'person_uuid, stake_id, unit_id, name, unit_name, baptism_date, birth_date, membership_duration, sex, friends, friends_count, ' +
  'aaronic_priesthood, melchizedek_priesthood, calling, ministering_brothers_sisters, ' +
  'ministering_assignment, temple_recommend, patriarchal_blessing, living_ordinance, ' +
  'family_name_prepared, first_temple_visit, details, photo_url, ' +
  'kind, baptism_goal_date, field_meta';

/** A loosely-typed member record (mirrors the Dart `Map<String, dynamic>`). */
export type Member = Record<string, unknown>;

export function str(m: Member, key: string): string {
  const v = m[key];
  return v == null ? '' : String(v);
}

// --- sync sentinels (mirror covenant_path/report.py + backend/db.py _SENTINELS) -----------------
// The backend writes these placeholder strings when a field couldn't be fetched this run (so the
// merge-upsert preserves last-good). They are TECHY/internal — only ADMINS should ever see the raw
// value; regular leaders get human-friendly text. (NEVER leak the raw sentinel into a leader's cell.)
export const NEEDS_PROFILE = 'needs-profile-api';
export const BLOCKED_PREFIX = 'blocked'; // 'blocked: insufficient calling access'

/** True when a value is one of the backend's internal sentinels (not real member data). */
export function isSentinel(v: unknown): boolean {
  const s = String(v ?? '');
  return s === NEEDS_PROFILE || s.startsWith(BLOCKED_PREFIX);
}

/**
 * Map a possibly-sentinel field value to what should be DISPLAYED, audience-aware:
 *  - admins see the raw sentinel verbatim (so they can diagnose "needs-profile-api" / "blocked: …");
 *  - everyone else sees friendly text — "Not available yet" for a pending/blocked field, never the
 *    raw techy string. A real value (Yes/No/Active/a date) is returned unchanged for both.
 * `blank` is what a non-admin sees for a sentinel ('—' in dense tables, 'Not available yet' in detail).
 */
export function displayFieldValue(
  v: unknown,
  isAdmin: boolean,
  blank: '—' | 'Not available yet' = 'Not available yet',
): string {
  const s = String(v ?? '');
  if (isSentinel(s)) return isAdmin ? s : blank;
  return s;
}

export function numOrNull(v: unknown): number | null {
  if (v == null) return null;
  const n = typeof v === 'number' ? v : Number(v);
  return Number.isFinite(n) ? n : null;
}

/** Stable identity for de-duping people in stat buckets (person_uuid → name → fallback). */
export function memberId(m: Member): string {
  const u = m['person_uuid'];
  if (u != null && String(u).length > 0) return String(u);
  const n = m['name'];
  if (n != null && String(n).length > 0) return String(n);
  return JSON.stringify(m);
}

export function isInvestigator(m: Member): boolean {
  return m['kind'] === 'investigator';
}

/** The rich one-work detail subtree, or null for rows synced before the schema change. */
export function detailsOf(m: Member): Record<string, unknown> | null {
  const d = m['details'];
  return d && typeof d === 'object' && !Array.isArray(d) ? (d as Record<string, unknown>) : null;
}

/** Per-field freshness map ({field:{f:last-fetched, t:last-tried}}, migration 0036), or {}. */
export function fieldMetaOf(m: Member): Record<string, { f?: string; t?: string }> {
  const fm = m['field_meta'];
  return fm && typeof fm === 'object' && !Array.isArray(fm)
    ? (fm as Record<string, { f?: string; t?: string }>)
    : {};
}

export type Freshness = 'fresh' | 'warn' | 'error' | 'never' | 'unknown';

/** Staleness of a field from its last-SUCCESSFUL fetch: >3d warn, >7d error, no fetch = never. */
export function freshness(m: Member, field: string): { state: Freshness; fetched?: string } {
  const meta = fieldMetaOf(m)[field];
  if (!meta) return { state: 'unknown' };
  if (!meta.f) return { state: 'never' };
  const days = (Date.now() - new Date(meta.f).getTime()) / 86_400_000;
  if (Number.isNaN(days)) return { state: 'unknown', fetched: meta.f };
  if (days > 7) return { state: 'error', fetched: meta.f };
  if (days > 3) return { state: 'warn', fetched: meta.f };
  return { state: 'fresh', fetched: meta.f };
}
