// A credential's `coverage.missing` (from the enrolled-stakes ops payload) is a list of OBJECTS, not
// strings: each is `{feature, granted_by[], also_unnamed_roles}` describing a covenant-path feature the
// authorizing calling can't reach and which callings grant it (built in lcr_client/access.py
// `_clean_missing`). The ops card used to `missing.join(', ')`, which stringifies each object to the
// literal "[object Object]" (the bug fixed 2026-06-18). Format each entry to its human feature label
// here — tolerant of the legacy plain-string shape — so the card reads e.g. "Ward leadership, …".

export interface CoverageMissing {
  feature?: string;
  granted_by?: string[];
  also_unnamed_roles?: number;
}

/** Human "what this calling can't see" line for the ops card. Maps the {feature,…} objects to their
 *  feature label, drops blanks, and joins; passes plain strings through unchanged. */
export function formatMissingFeatures(missing: unknown): string {
  if (!Array.isArray(missing)) return '';
  return missing
    .map((m) => (typeof m === 'string' ? m : String((m as CoverageMissing)?.feature ?? '')))
    .filter(Boolean)
    .join(', ');
}
