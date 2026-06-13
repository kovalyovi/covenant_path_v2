// Manual (leader-added) people being taught + the merge-with-real logic (item 11). A manual member is
// tracked before LCR has a record; when the daily sync later brings a REAL record that matches by name
// WITHIN THE SAME UNIT, we SUGGEST a merge (never auto). Merging is a FULL remote override EXCEPT the
// custom notes, which are preserved. Pure so it unit-tests and mirrors in the native ports.

import type { Member } from '../lib/member';

export interface ManualMember {
  id: string;
  stake_id?: string | null;
  unit_id?: string | null;
  unit_name?: string | null;
  name: string;
  custom_notes?: string | null;
  created_by?: string | null;
  merged_at?: string | null;
  merged_into_uuid?: string | null;
}

/** Normalize a person name for matching: lowercased, diacritics folded, punctuation/extra-space
 *  stripped, and a "Surname, Given" form folded to the same token set as "Given Surname"
 *  (order-insensitive). So "Smith, John" matches "John Smith" and "José García" matches "Jose Garcia". */
export function normalizeName(name: string): string {
  const tokens = String(name ?? '')
    .toLowerCase()
    // Fold diacritics so an accented name matches its ASCII form — LCR often stores "Jose Garcia"
    // while a leader types "José García" (and vice-versa). Decompose then drop the combining marks
    // (é→e, í→i, ñ→n) BEFORE the ASCII filter, which would otherwise delete the letter outright.
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/[.,]/g, ' ')
    .replace(/['’-]/g, '')           // drop apostrophes/hyphens: "O'Brien"/"Mary-Jane" match plain forms
    .replace(/[^a-z0-9\s]/g, '')
    .split(/\s+/)
    .filter(Boolean)
    .sort();
  return tokens.join(' ');
}

/** Same unit? Prefer unit_id when both sides have it; else fall back to unit_name. */
function sameUnit(a: ManualMember, m: Member): boolean {
  const aUnitId = a.unit_id ?? null;
  const mUnitId = (m['unit_id'] as string | null | undefined) ?? null;
  if (aUnitId && mUnitId) return aUnitId === mUnitId;
  const aName = (a.unit_name ?? '').trim().toLowerCase();
  const mName = String(m['unit_name'] ?? '').trim().toLowerCase();
  return aName.length > 0 && aName === mName;
}

/** The real member that matches a manual one (by normalized name within the SAME unit), or null. Only
 *  considers not-yet-merged manual members and skips a real member with no usable person_uuid. */
export function findMatch(manual: ManualMember, members: Member[]): Member | null {
  if (manual.merged_at) return null;
  const want = normalizeName(manual.name);
  if (!want) return null;
  for (const m of members) {
    if (!m['person_uuid']) continue;
    if (!sameUnit(manual, m)) continue;
    if (normalizeName(String(m['name'] ?? '')) === want) return m;
  }
  return null;
}

export interface MergeSuggestion {
  manual: ManualMember;
  match: Member;
}

/** All manual→real merge suggestions for the current data (one per matched, unmerged manual member). */
export function mergeSuggestions(manuals: ManualMember[], members: Member[]): MergeSuggestion[] {
  const out: MergeSuggestion[] = [];
  for (const manual of manuals) {
    const match = findMatch(manual, members);
    if (match) out.push({ manual, match });
  }
  return out;
}

export interface MergePlan {
  /** the real member's person_uuid the merge resolves to (notes attach here) */
  personUuid: string;
  /** the note to preserve on the real member (the manual member's custom notes) */
  preservedNote: string;
  /** the manual member id to mark merged */
  manualId: string;
}

/** Build the merge plan: the remote record is the full override (we keep the real member as-is); the
 *  ONLY thing carried over is the manual member's custom notes, preserved onto the real member. */
export function planMerge(manual: ManualMember, match: Member): MergePlan {
  return {
    personUuid: String(match['person_uuid']),
    preservedNote: (manual.custom_notes ?? '').trim(),
    manualId: manual.id,
  };
}

/** Combine a preserved manual note with whatever single note the real member already has — the
 *  remote member's other fields fully override, but NOTES are never lost. If the real member already
 *  has a note, append the preserved one under a divider; else use the preserved note alone. */
export function mergedNote(existingNote: string, preserved: string): string {
  const a = (existingNote ?? '').trim();
  const b = (preserved ?? '').trim();
  if (!b) return a;
  if (!a) return b;
  if (a.includes(b)) return a; // already contains it (idempotent re-merge)
  return `${a}\n\n${b}`;
}
