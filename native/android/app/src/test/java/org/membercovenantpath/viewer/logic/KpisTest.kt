package org.membercovenantpath.viewer.logic

import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.membercovenantpath.viewer.model.Member
import org.membercovenantpath.viewer.model.SacramentEntry
import java.time.LocalDate

/**
 * Verifies the KPI bucketing/series math matches dashboard_common.dart + kpis_view.dart exactly:
 * fixed windows anchored to today, unique-people-per-bucket, the preceding-window overlay, and the
 * ALL data-span granularity switch. Uses a fixed [today] so the windows are deterministic.
 */
class KpisTest {

    private val today = LocalDate.of(2026, 6, 1) // a Monday

    private val json = Json { ignoreUnknownKeys = true; isLenient = true }

    private fun memberWithSacrament(id: String, vararg dates: String): Member {
        val sac = dates.joinToString(",") { """{"label":"x","attended":true,"date":"$it"}""" }
        val raw = json.parseToJsonElement("""{"sacrament":[$sac]}""")
        return Member(personUuid = id, details = raw as kotlinx.serialization.json.JsonObject, unitName = "Ward A")
    }

    @Test fun monthWindowHasFiveWeeklyBuckets() {
        // Data in the first (4 weeks ago) AND last (this week) bucket so the N9 trim keeps all 5.
        val people = listOf(
            memberWithSacrament("first", today.minusDays(28).toString()),
            memberWithSacrament("last", today.toString()),
        )
        val m = Kpis.metricData(people, { Kpis.attendedDates(it) }, KpiPeriod.MONTH, today)
        assertEquals(5, m.series.labels.size)
        assertEquals(5, m.series.current.size)
        // previous-window overlay is also 5 buckets
        assertEquals(5, m.series.prev.size)
    }

    @Test fun yearWindowHasTwelveMonthlyBuckets() {
        // First (Jul 2025) AND current (Jun 2026) month populated → trim keeps the full 12 buckets.
        val people = listOf(
            memberWithSacrament("first", today.minusMonths(11).toString()),
            memberWithSacrament("last", today.toString()),
        )
        val m = Kpis.metricData(people, { Kpis.attendedDates(it) }, KpiPeriod.YEAR, today)
        assertEquals(12, m.series.labels.size)
        // ends on the current month
        assertEquals("Jun", m.series.labels.last())
    }

    @Test fun emptyWindowCollapsesToEmptySeries() {
        // N9: no data → no padded-0 buckets (so the chart shows its empty state, not a flat line).
        val month = Kpis.metricData(emptyList(), { Kpis.attendedDates(it) }, KpiPeriod.MONTH, today)
        assertTrue(month.series.labels.isEmpty())
        assertTrue(month.series.current.isEmpty())
        assertTrue(month.events.isEmpty())
        val year = Kpis.metricData(emptyList(), { Kpis.attendedDates(it) }, KpiPeriod.YEAR, today)
        assertTrue(year.series.labels.isEmpty())
    }

    @Test fun trimsToDataSpanWhenLeadingMonthsEmpty() {
        // Only the current week has data → MONTH collapses to that single bucket (not 5 with four 0s).
        val people = listOf(memberWithSacrament("p1", today.toString()))
        val m = Kpis.metricData(people, { Kpis.attendedDates(it) }, KpiPeriod.MONTH, today)
        assertEquals(1, m.series.labels.size)
        assertEquals(1.0, m.series.current.last(), 1e-9)
        assertEquals(0, m.events.first().bucket) // event rebucketed to the trimmed index
    }

    @Test fun uniquePeoplePerBucketCountedOnce() {
        // Same person attends twice in the current week → counts as 1 in that bucket.
        val people = listOf(memberWithSacrament("p1", today.toString(), today.minusDays(1).toString()))
        val m = Kpis.metricData(people, { Kpis.attendedDates(it) }, KpiPeriod.MONTH, today)
        assertEquals(1.0, m.series.current.last(), 1e-9)
        // two distinct people in the same week → 2
        val two = listOf(
            memberWithSacrament("a", today.toString()),
            memberWithSacrament("b", today.toString()),
        )
        val m2 = Kpis.metricData(two, { Kpis.attendedDates(it) }, KpiPeriod.MONTH, today)
        assertEquals(2.0, m2.series.current.last(), 1e-9)
    }

    @Test fun eventsMapToBucketIndexForDrill() {
        val people = listOf(memberWithSacrament("p1", today.toString()))
        val m = Kpis.metricData(people, { Kpis.attendedDates(it) }, KpiPeriod.MONTH, today)
        // the single event lands in the last (current-week) bucket
        assertEquals(1, m.events.size)
        assertEquals(m.series.labels.size - 1, m.events.first().bucket)
    }

    @Test fun allSwitchesToYearBucketsForLongHistory() {
        // Spread spanning >36 months → ALL groups by YEAR.
        val people = listOf(
            memberWithSacrament("old", "2021-01-03"),
            memberWithSacrament("new", today.toString()),
        )
        val m = Kpis.metricData(people, { Kpis.attendedDates(it) }, KpiPeriod.ALL, today)
        // years 2021..2026 inclusive = 6 buckets, labeled as plain years
        assertEquals(listOf("2021", "2022", "2023", "2024", "2025", "2026"), m.series.labels)
    }

    @Test fun allUsesMonthBucketsForShortHistory() {
        val people = listOf(memberWithSacrament("a", "2026-04-05"), memberWithSacrament("b", today.toString()))
        val m = Kpis.metricData(people, { Kpis.attendedDates(it) }, KpiPeriod.ALL, today)
        // Apr, May, Jun 2026 → 3 monthly buckets (current-year labels are bare month names)
        assertEquals(listOf("Apr", "May", "Jun"), m.series.labels)
    }

    @Test fun lessonsWithMemberCountsPresentLessons() {
        val raw = json.parseToJsonElement(
            """{"lessons":[
                 {"name":"L1","principles":[{"name":"p","memberPresent":true,"taughtLevel":1}]},
                 {"name":"L2","principles":[{"name":"p","memberPresent":false,"taughtLevel":1}]}
               ]}""",
        ) as kotlinx.serialization.json.JsonObject
        val m = Member(personUuid = "x", details = raw)
        assertEquals(1, Kpis.lessonsWithMember(listOf(m)))
        assertEquals(1, Kpis.membersWithMemberLessons(listOf(m)).size)
        assertEquals(1, Kpis.membersWithMemberLessons(listOf(m)).first().count)
    }

    @Test fun baptismsByMonthTrimsToSpan() {
        // Two baptisms three months apart inside a 12-month window → 4 contiguous months (Mar…Jun),
        // not the full 12 with leading 0s. Total still reflects the data; events rebucket to the span.
        val people = listOf(
            Member(personUuid = "a", baptismDate = "2026-03-15", unitName = "A"),
            Member(personUuid = "b", baptismDate = "2026-06-01", unitName = "A"),
        )
        val r = Kpis.baptismsByMonth(people, BaptismWindow.M12, today)
        assertEquals(listOf("Mar", "Apr", "May", "Jun"), r.labels)
        assertEquals(listOf(1.0, 0.0, 0.0, 1.0), r.counts)
        assertEquals(2, r.total)
        assertEquals(listOf(0, 3), r.events.map { it.bucket }.sorted())
    }

    @Test fun periodRangeLabelOnlyForMonthAndYear() {
        assertTrue(Kpis.periodRangeLabel(KpiPeriod.MONTH, today) != null)
        assertTrue(Kpis.periodRangeLabel(KpiPeriod.YEAR, today) != null)
        assertEquals(null, Kpis.periodRangeLabel(KpiPeriod.ALL, today))
    }

    // ---- sacrament attendance health (#1e / #10b) ----

    @Test fun attendanceBucketLevels() {
        assertEquals(Kpis.AttendanceLevel.UNKNOWN, Kpis.attendanceBucket(null).level)
        assertEquals("—", Kpis.attendanceBucket(null).label)
        assertEquals(Kpis.AttendanceLevel.GREAT, Kpis.attendanceBucket(8 to 8).level)
        assertEquals(Kpis.AttendanceLevel.GREAT, Kpis.attendanceBucket(7 to 8).level)
        assertEquals(Kpis.AttendanceLevel.FAIR, Kpis.attendanceBucket(5 to 8).level)
        assertEquals(Kpis.AttendanceLevel.POOR, Kpis.attendanceBucket(2 to 8).level)
        val none = Kpis.attendanceBucket(0 to 8)
        assertEquals(Kpis.AttendanceLevel.NONE, none.level)
        assertTrue(none.bold)        // 0-of-window is the only BOLD signal
        assertEquals("0/8", none.label)
        assertTrue(!Kpis.attendanceBucket(7 to 8).bold)
    }

    @Test fun sacramentWindowTakesEightNewest() {
        // 10 weekly entries out of date order; window = the 8 NEWEST. Mark the 2 OLDEST as missed.
        val entries = (0 until 10).map { i ->
            SacramentEntry(label = "w$i", attended = i < 8, date = today.minusWeeks(i.toLong()).toString())
        }.shuffled()
        val win = Kpis.sacramentWindow(entries)!!
        assertEquals(8, win.second)  // capped at the window size
        assertEquals(8, win.first)   // the 8 newest were all attended (oldest-2 misses excluded)
    }

    @Test fun sacramentWindowNullWhenNoList() {
        assertNull(Kpis.sacramentWindow(null))
        assertNull(Kpis.sacramentWindow(emptyList()))
    }
}
