package org.membercovenantpath.viewer.logic

import org.membercovenantpath.viewer.model.NoteRow

/**
 * Latest-note index for list rows — built from ONE bulk member_comments query per stake load
 * (RLS scopes the rows server-side with the same policy as members). Pure logic, mirrored from
 * the web's `logic/notes.ts` (`buildNotesIndex`) and Swift's `Logic/NotesIndex.swift`.
 */

/** The newest leader note on a member + how many there are in total. */
data class NoteSummary(val count: Int, val latest: String, val latestAt: String)

object NotesIndex {
    /** person_uuid -> newest note + count. Rows without a uuid or with a blank body are skipped. */
    fun build(rows: List<NoteRow>): Map<String, NoteSummary> {
        val out = LinkedHashMap<String, NoteSummary>()
        for (r in rows) {
            val uuid = r.memberPersonUuid.orEmpty()
            if (uuid.isEmpty()) continue
            val body = r.body?.trim().orEmpty()
            if (body.isEmpty()) continue
            val at = r.createdAt.orEmpty()
            val cur = out[uuid]
            out[uuid] = when {
                cur == null -> NoteSummary(1, body, at)
                // ISO timestamps from one column share a format, so string compare orders correctly.
                at >= cur.latestAt -> NoteSummary(cur.count + 1, body, at)
                else -> cur.copy(count = cur.count + 1)
            }
        }
        return out
    }
}
