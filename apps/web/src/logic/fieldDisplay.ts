// The CLIENT DISPLAY CONTRACT for any field value, applied everywhere a field is shown (table,
// cards, details). One small helper so the table, person cards, and detail views all agree.
//
// Three outcomes for a field value:
//   • a real value (Yes/No/Active/a date/…)  → status 'value'  → show it verbatim.
//   • "N/A"                                   → status 'na'     → NOT ELIGIBLE; show quietly as "N/A"
//                                                                  (or OMIT in Golden Hour). NEVER a warning.
//   • the "needs-profile-api" sentinel, the "blocked: …" sentinel, OR null/empty
//                                             → status 'issue'  → a DATA ISSUE (we should have it but
//                                                                  don't); show a ⚠ warning indicator,
//                                                                  NEVER the raw sentinel string.
//
// `isSentinel` / `NEEDS_PROFILE` already live in lib/member (the backend-sentinel recognizer); this
// builds the user-facing three-way classification on top of it. Critically — per the user's rule —
// the sentinel AND null/empty are treated THE SAME: both are a ⚠ data issue.

import { isSentinel, isAdminSentinel } from '../lib/member';
import { isNA } from './milestones';

export type FieldStatus = 'value' | 'na' | 'issue';

export interface FieldDisplay {
  status: FieldStatus;
  /** What to render as text: the real value, the literal "N/A", or "" for a data issue (the caller
   *  shows a ⚠ indicator instead of text). For an admin a data-issue value keeps the raw sentinel so
   *  they can diagnose it; a leader never sees the techy string. */
  text: string;
  /** True only for status 'issue' — the caller renders a ⚠ warning indicator. */
  warn: boolean;
}

/**
 * Classify a field value into the display contract above.
 *  - `isAdmin` only affects a data ISSUE: an admin sees the raw sentinel as the text (still warn:true)
 *    so they can diagnose "needs-profile-api"/"blocked: …"; a leader sees empty text + the ⚠ only.
 */
export function fieldDisplay(v: unknown, isAdmin = false): FieldDisplay {
  // N/A first — "not eligible" is a quiet, legitimate state, never a warning.
  if (isNA(v)) return { status: 'na', text: 'N/A', warn: false };
  const s = String(v ?? '').trim();
  // The backend sentinel OR an empty/missing value are BOTH a data issue (treated the same).
  if (s === '' || isSentinel(s)) {
    // Admins keep the raw sentinel string for diagnosis (only when it IS a sentinel — an empty value
    // has nothing techy to show); leaders never see it.
    const adminText = isAdmin && isAdminSentinel(s) ? s : '';
    return { status: 'issue', text: adminText, warn: true };
  }
  return { status: 'value', text: s, warn: false };
}

/** Convenience: is this value a data issue (sentinel OR null/empty, but NOT N/A)? */
export function isDataIssue(v: unknown): boolean {
  return fieldDisplay(v).status === 'issue';
}
