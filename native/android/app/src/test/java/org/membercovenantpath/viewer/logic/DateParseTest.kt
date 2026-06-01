package org.membercovenantpath.viewer.logic

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import java.time.LocalDate

/** Verifies DateParse mirrors golden_hour.dart / dashboard_common.dart date handling. */
class DateParseTest {

    @Test fun parsesIso() {
        assertEquals(LocalDate.of(2026, 2, 6), DateParse.parseMemberDate("2026-02-06"))
    }

    @Test fun parsesIsoTimestamp() {
        assertEquals(LocalDate.of(2026, 2, 6), DateParse.parseMemberDate("2026-02-06T12:00:00Z"))
    }

    @Test fun parsesDayMonthYear() {
        assertEquals(LocalDate.of(2026, 2, 6), DateParse.parseMemberDate("6 Feb 2026"))
        assertEquals(LocalDate.of(2025, 12, 31), DateParse.parseMemberDate("31 December 2025"))
    }

    @Test fun parsesMonthDayYearSlash() {
        assertEquals(LocalDate.of(2026, 2, 6), DateParse.parseMemberDate("2/6/2026"))
        assertEquals(LocalDate.of(2026, 2, 6), DateParse.parseMemberDate("2/6/26"))
    }

    @Test fun sentinelsAreNull() {
        assertNull(DateParse.parseMemberDate(null))
        assertNull(DateParse.parseMemberDate(""))
        assertNull(DateParse.parseMemberDate("N/A"))
        assertNull(DateParse.parseMemberDate("needs-profile-api"))
        assertNull(DateParse.parseMemberDate("blocked: insufficient calling access"))
    }

    @Test fun yearOfExtractsFirstFourDigits() {
        assertEquals(1990, DateParse.yearOf("1990-05-01"))
        assertEquals(2001, DateParse.yearOf("born 2001"))
        assertNull(DateParse.yearOf("unknown"))
    }

    @Test fun ageNowFromFullDate() {
        val today = LocalDate.of(2026, 5, 31)
        // Birthday already passed this year.
        assertEquals(36, DateParse.ageNow("1990-01-01", today))
        // Birthday later this year → not yet had it.
        assertEquals(35, DateParse.ageNow("1990-12-31", today))
    }

    @Test fun ageNowFromYearOnly() {
        val today = LocalDate.of(2026, 5, 31)
        assertEquals(36, DateParse.ageNow("1990", today))
    }

    @Test fun memberOneYearPlusByBaptismDate() {
        val today = LocalDate.of(2026, 5, 31)
        // 400 days ago → ≥1 year.
        assert(DateParse.memberOneYearPlus("2025-04-26", null, today))
        // 100 days ago → not yet.
        assert(!DateParse.memberOneYearPlus("2026-02-20", null, today))
    }

    @Test fun memberOneYearPlusByDurationText() {
        val today = LocalDate.of(2026, 5, 31)
        assert(DateParse.memberOneYearPlus(null, "Member for 2 years", today))
        assert(!DateParse.memberOneYearPlus(null, "Member for 8 months", today))
    }

    @Test fun monthsDaysAgoFormatsCalendarAware() {
        val today = LocalDate.of(2026, 5, 31)
        assertEquals("2 months 25 days", DateParse.monthsDaysAgo(LocalDate.of(2026, 3, 6), today))
        assertEquals("", DateParse.monthsDaysAgo(LocalDate.of(2027, 1, 1), today)) // future
    }
}
