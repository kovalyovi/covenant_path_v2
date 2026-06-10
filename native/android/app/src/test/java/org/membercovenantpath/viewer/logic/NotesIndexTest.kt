package org.membercovenantpath.viewer.logic

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.membercovenantpath.viewer.model.NoteRow

/** Mirrors web `src/test/notes.test.ts` and Swift `LogicTests` notes-index tests. */
class NotesIndexTest {

    private fun row(uuid: String?, body: String?, at: String?) =
        NoteRow(memberPersonUuid = uuid, body = body, createdAt = at)

    @Test
    fun keepsNewestNotePerMemberAndCounts() {
        val idx = NotesIndex.build(
            listOf(
                row("a", "older", "2026-06-01T10:00:00+00:00"),
                row("a", "newest", "2026-06-09T10:00:00+00:00"),
                row("a", "middle", "2026-06-05T10:00:00+00:00"),
                row("b", "only one", "2026-06-02T10:00:00+00:00"),
            ),
        )
        assertEquals(NoteSummary(3, "newest", "2026-06-09T10:00:00+00:00"), idx["a"])
        assertEquals(NoteSummary(1, "only one", "2026-06-02T10:00:00+00:00"), idx["b"])
    }

    @Test
    fun orderIndependent() {
        val rows = listOf(
            row("a", "second", "2026-06-08T10:00:00+00:00"),
            row("a", "first", "2026-06-07T10:00:00+00:00"),
        )
        assertEquals("second", NotesIndex.build(rows)["a"]?.latest)
        assertEquals("second", NotesIndex.build(rows.reversed())["a"]?.latest)
    }

    @Test
    fun skipsBlankBodyAndMissingUuid() {
        val idx = NotesIndex.build(
            listOf(
                row("", "no uuid", "2026-06-01T00:00:00Z"),
                row("a", "   ", "2026-06-01T00:00:00Z"),
                row("a", null, "2026-06-01T00:00:00Z"),
                row(null, "x", "2026-06-01T00:00:00Z"),
            ),
        )
        assertTrue(idx.isEmpty())
    }

    @Test
    fun missingCreatedAtStillCounts() {
        val idx = NotesIndex.build(
            listOf(
                row("a", "undated", null),
                row("a", "dated", "2026-06-01T00:00:00Z"),
            ),
        )
        assertEquals(2, idx["a"]?.count)
        assertEquals("dated", idx["a"]?.latest)
    }
}
