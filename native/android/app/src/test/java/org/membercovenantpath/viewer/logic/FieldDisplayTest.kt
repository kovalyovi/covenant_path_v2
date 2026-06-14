package org.membercovenantpath.viewer.logic

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Verifies the field-display contract matches the web `apps/web/src/logic/fieldDisplay.ts` exactly:
 * a real value shows verbatim, N/A is a quiet not-eligible state (never a warning), and the
 * needs-profile-api / blocked sentinels AND null/empty are BOTH a data issue (warn) — with the raw
 * sentinel surfaced only to admins.
 */
class FieldDisplayTest {

    @Test fun realValueShowsVerbatim() {
        val r = FieldDisplay.classify("Yes")
        assertEquals(FieldDisplay.Status.VALUE, r.status)
        assertEquals("Yes", r.text)
        assertFalse(r.warn)
        // A genuine recorded "No" is a real value, never a warning.
        assertEquals(FieldDisplay.Status.VALUE, FieldDisplay.classify("No").status)
        // Trims surrounding whitespace.
        assertEquals("Active", FieldDisplay.classify("  Active  ").text)
    }

    @Test fun naIsQuietNeverAWarning() {
        val r = FieldDisplay.classify("N/A")
        assertEquals(FieldDisplay.Status.NA, r.status)
        assertEquals("N/A", r.text)
        assertFalse(r.warn)
        // Case-insensitive (matches isNA's uppercasing).
        assertEquals(FieldDisplay.Status.NA, FieldDisplay.classify("n/a").status)
        // N/A is NOT a data issue.
        assertFalse(FieldDisplay.isDataIssue("N/A"))
    }

    @Test fun sentinelIsADataIssueWarningNeverRawForLeaders() {
        val r = FieldDisplay.classify("needs-profile-api", isAdmin = false)
        assertEquals(FieldDisplay.Status.ISSUE, r.status)
        assertTrue(r.warn)
        // A leader NEVER sees the raw techy string.
        assertEquals("", r.text)
        // blocked: … is also a sentinel.
        assertEquals(FieldDisplay.Status.ISSUE, FieldDisplay.classify("blocked: insufficient calling access").status)
    }

    @Test fun adminSeesTheRawSentinelToDiagnose() {
        val r = FieldDisplay.classify("needs-profile-api", isAdmin = true)
        assertEquals(FieldDisplay.Status.ISSUE, r.status)
        assertTrue(r.warn)
        // Admin keeps the raw string for diagnosis.
        assertEquals("needs-profile-api", r.text)
        assertEquals(
            "blocked: insufficient calling access",
            FieldDisplay.classify("blocked: insufficient calling access", isAdmin = true).text,
        )
    }

    @Test fun nullOrEmptyIsTreatedTheSameAsASentinel() {
        // Per the user's rule: null/empty is a DATA ISSUE just like the sentinel.
        for (v in listOf(null, "", "   ")) {
            val r = FieldDisplay.classify(v)
            assertEquals(FieldDisplay.Status.ISSUE, r.status)
            assertTrue(r.warn)
            assertEquals("", r.text)
        }
        // An empty value has NO techy string, so even an admin sees empty text (only a sentinel has
        // something to surface).
        assertEquals("", FieldDisplay.classify("", isAdmin = true).text)
        assertTrue(FieldDisplay.isDataIssue(null))
        assertTrue(FieldDisplay.isDataIssue(""))
    }

    @Test fun isSentinelRecognizer() {
        assertTrue(FieldDisplay.isSentinel("needs-profile-api"))
        assertTrue(FieldDisplay.isSentinel("blocked: foo"))
        assertFalse(FieldDisplay.isSentinel("Yes"))
        assertFalse(FieldDisplay.isSentinel(""))
        assertFalse(FieldDisplay.isSentinel(null))
    }
}
