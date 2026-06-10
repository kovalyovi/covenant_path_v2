// Latest-note index for list rows — built from ONE bulk member_comments query per stake load
// (RLS scopes the rows server-side with the same policy as members, so the query is automatically
// limited to people the viewer can see). Pure so it unit-tests and mirrors 1:1 in Swift
// (Logic/NotesIndex.swift) and Kotlin (logic/NotesIndex.kt).

export interface NoteRow {
  member_person_uuid?: string | null;
  body?: string | null;
  created_at?: string | null;
}

export interface NoteSummary {
  /** total notes on this member */
  count: number;
  /** body of the newest note */
  latest: string;
  /** created_at of the newest note (ISO) */
  latestAt: string;
}

export function buildNotesIndex(rows: NoteRow[]): Record<string, NoteSummary> {
  const out: Record<string, NoteSummary> = {};
  for (const r of rows) {
    const uuid = r.member_person_uuid ?? '';
    const body = (r.body ?? '').trim();
    if (!uuid || !body) continue;
    const at = r.created_at ?? '';
    const cur = out[uuid];
    if (!cur) {
      out[uuid] = { count: 1, latest: body, latestAt: at };
    } else {
      cur.count += 1;
      // ISO timestamps from one column share a format, so string compare orders correctly.
      if (at >= cur.latestAt) {
        cur.latest = body;
        cur.latestAt = at;
      }
    }
  }
  return out;
}
