package org.membercovenantpath.viewer.logic

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import org.membercovenantpath.viewer.ui.theme.StatusColors
import java.time.Instant
import java.time.temporal.ChronoUnit

/** Verifies the freshness "ago" + staleness color thresholds match dashboard_common.dart. */
class FreshnessTest {

    private val now = Instant.parse("2026-06-01T12:00:00Z")

    @Test fun agoBuckets() {
        assertEquals("just now", Freshness.ago(now.toString(), now))
        assertEquals("30m ago", Freshness.ago(now.minus(30, ChronoUnit.MINUTES).toString(), now))
        assertEquals("3h ago", Freshness.ago(now.minus(3, ChronoUnit.HOURS).toString(), now))
        assertEquals("5d ago", Freshness.ago(now.minus(5, ChronoUnit.DAYS).toString(), now))
    }

    @Test fun staleColorThresholds() {
        assertNull(Freshness.staleColor(now.minus(1, ChronoUnit.DAYS).toString(), now)) // fresh
        assertEquals(StatusColors.NextAmber, Freshness.staleColor(now.minus(3, ChronoUnit.DAYS).toString(), now))
        assertEquals(StatusColors.NoRed, Freshness.staleColor(now.minus(20, ChronoUnit.DAYS).toString(), now))
        assertEquals(StatusColors.NoRed, Freshness.staleColor(null, now)) // never synced reads stale
    }
}
