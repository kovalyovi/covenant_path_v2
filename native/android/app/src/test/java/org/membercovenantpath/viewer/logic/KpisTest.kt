package org.membercovenantpath.viewer.logic

import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.membercovenantpath.viewer.model.Member
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
        val m = Kpis.metricData(emptyList(), { Kpis.attendedDates(it) }, KpiPeriod.MONTH, today)
        assertEquals(5, m.series.labels.size)
        assertEquals(5, m.series.current.size)
        // previous-window overlay is also 5 buckets
        assertEquals(5, m.series.prev.size)
    }

    @Test fun yearWindowHasTwelveMonthlyBuckets() {
        val m = Kpis.metricData(emptyList(), { Kpis.attendedDates(it) }, KpiPeriod.YEAR, today)
        assertEquals(12, m.series.labels.size)
        // ends on the current month
        assertEquals("Jun", m.series.labels.last())
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

    @Test fun periodRangeLabelOnlyForMonthAndYear() {
        assertTrue(Kpis.periodRangeLabel(KpiPeriod.MONTH, today) != null)
        assertTrue(Kpis.periodRangeLabel(KpiPeriod.YEAR, today) != null)
        assertEquals(null, Kpis.periodRangeLabel(KpiPeriod.ALL, today))
    }
}
