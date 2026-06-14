// Single-note model (item 8): ONE editable leader note per member. The durable note lives in
// `member_notes` (one row per member); the legacy `member_comments` thread is FOLDED into a single
// text on read so existing notes survive, then written back as one field. Pure so it unit-tests and
// mirrors 1:1 in Swift (Logic/NotesIndex.swift) and Kotlin (logic/NotesIndex.kt).

export interface NoteRow {
  member_person_uuid?: string | null;
  body?: string | null;
  author_name?: string | null;
  author_email?: string | null;
  created_at?: string | null;
}

/** A single editable note row (member_notes). */
export interface MemberNoteRow {
  member_person_uuid?: string | null;
  note?: string | null;
  updated_at?: string | null;
}

export interface NoteSummary {
  /** the FULL single note for this member (shown in full on the main screen + edited inline) */
  text: string;
  /** when it was last updated (ISO), for ordering/freshness */
  updatedAt: string;
}

/** One thread entry (member_comments) — the model the cards + detail editor render directly. */
export interface NoteThreadEntry {
  id?: string;
  body: string;
  author_name?: string | null;
  author_email?: string | null;
  created_at: string;
  updated_at?: string | null;
}

/** "Mar 5, 2026" from an ISO timestamp, for the inline author/date prefix when folding a thread. */
function shortDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  return `${MONTHS[d.getMonth()]} ${d.getDate()}, ${d.getFullYear()}`;
}

/** Fold a member's legacy comment thread into ONE text, oldest→newest, preserving each comment's
 *  author + date inline as a small prefix. This is what a member with no single-note row yet shows;
 *  saving it writes the result back to member_notes as the single field. Empty thread → "". */
export function foldComments(rows: NoteRow[]): string {
  const ordered = [...rows]
    .filter((r) => (r.body ?? '').trim().length > 0)
    .sort((a, b) => (a.created_at ?? '').localeCompare(b.created_at ?? ''));
  return ordered
    .map((r) => {
      const who = (r.author_name ?? r.author_email ?? '').trim();
      const when = r.created_at ? shortDate(r.created_at) : '';
      const head = [who, when].filter(Boolean).join(' · ');
      const body = (r.body ?? '').trim();
      return head ? `${head}\n${body}` : body;
    })
    .join('\n\n');
}

/** Build the per-member single-note index for list rows. The durable member_notes row WINS; a member
 *  with only legacy comments shows the folded thread (so nothing is lost before the first edit). Both
 *  sources are RLS-scoped server-side like members. */
export function buildNotesIndex(
  notes: MemberNoteRow[],
  comments: NoteRow[] = [],
): Record<string, NoteSummary> {
  const out: Record<string, NoteSummary> = {};

  // 1) Fold legacy comment threads first (lower priority).
  const byMember = new Map<string, NoteRow[]>();
  for (const c of comments) {
    const uuid = c.member_person_uuid ?? '';
    if (!uuid) continue;
    if (!byMember.has(uuid)) byMember.set(uuid, []);
    byMember.get(uuid)!.push(c);
  }
  for (const [uuid, rows] of byMember) {
    const text = foldComments(rows).trim();
    if (!text) continue;
    const latestAt = rows.reduce((m, r) => ((r.created_at ?? '') > m ? (r.created_at ?? '') : m), '');
    out[uuid] = { text, updatedAt: latestAt };
  }

  // 2) The durable single note overrides the folded thread when present.
  for (const n of notes) {
    const uuid = n.member_person_uuid ?? '';
    const text = (n.note ?? '').trim();
    if (!uuid) continue;
    if (text) {
      out[uuid] = { text, updatedAt: n.updated_at ?? '' };
    } else {
      // An explicit empty note row means the leader cleared it — don't resurrect the old thread.
      delete out[uuid];
    }
  }
  return out;
}
