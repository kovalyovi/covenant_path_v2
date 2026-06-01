package org.membercovenantpath.viewer.logic

import org.membercovenantpath.viewer.model.Member
import org.membercovenantpath.viewer.model.parsedDetails
import java.time.LocalDate
import java.time.format.DateTimeFormatter
import java.util.Locale

/**
 * KPI time-series math, ported 1:1 from views/dashboard_common.dart + views/kpis_view.dart
 * (`_metricData`, `_bucketKey`, `_windowBuckets`, `allByYear`, `_attendedDates`, `_firstLessonDate`,
 * `_lessonsWithMember`, `_unitCompletion`, `_membersWithMemberLessons`) and the `_KpiView`
 * period-range labels. PURE Kotlin (injectable [today]) so it's unit-tested apples-to-apples.
 *
 * Fixed windows anchored to TODAY (not "the last N buckets that have data"):
 *   Month = the 5 WEEKS ending this week (weekly buckets)
 *   Year  = the 12 MONTHS ending this month (monthly buckets)
 *   All   = first data → now, by MONTH (≤3 yrs) or by YEAR (longer). Empty buckets render as zeros.
 * The prev overlay is the immediately-preceding equal span.
 */
enum class KpiPeriod { MONTH, YEAR, ALL }

/** A chart series: current window (labels+values) overlaid against the preceding equal window. */
data class KpiSeries(
    val labels: List<String>,
    val current: List<Double>,
    val prev: List<Double>,
)

/** One matching event for a drill-down: a member counted on a date, mapped to its window bucket idx. */
data class KpiEvent(val member: Member, val date: LocalDate, val bucket: Int)

/** The series + the underlying events (so a tap can show *who*, by unit or chronologically). */
data class KpiMetric(val series: KpiSeries, val events: List<KpiEvent>)

object Kpis {

    private val MD = DateTimeFormatter.ofPattern("M/d", Locale.US)   // "2/6"
    private val MON = DateTimeFormatter.ofPattern("MMM", Locale.US)  // "Feb"
    private val MD_LONG = DateTimeFormatter.ofPattern("MMM d", Locale.US)
    private val MD_Y = DateTimeFormatter.ofPattern("MMM d, yyyy", Locale.US)
    private val M_Y = DateTimeFormatter.ofPattern("MMM yyyy", Locale.US)
    private val MON_YY = DateTimeFormatter.ofPattern("MMM ''yy", Locale.US) // "Feb '25"

    private fun weekStart(d: LocalDate): LocalDate = d.minusDays((d.dayOfWeek.value - 1).toLong()) // Monday

    /** Bucket key (stable, sortable int) for an event date under [p] — must match windowBuckets. */
    private fun bucketKey(dt: LocalDate, p: KpiPeriod, allByYear: Boolean): Int = when (p) {
        KpiPeriod.MONTH -> {
            val w = weekStart(dt)
            w.year * 10000 + w.monthValue * 100 + w.dayOfMonth
        }
        KpiPeriod.YEAR -> dt.year * 100 + dt.monthValue
        KpiPeriod.ALL -> if (allByYear) dt.year else dt.year * 100 + dt.monthValue
    }

    /**
     * Ordered (key,label) buckets of the window ending [today], shifted back [shift] windows
     * (shift=1 → the preceding equal span). ALL is data-driven (handled in [metricData]) → empty here.
     */
    private fun windowBuckets(p: KpiPeriod, today: LocalDate, shift: Int): List<Pair<Int, String>> = when (p) {
        KpiPeriod.MONTH -> {
            val end = weekStart(today).minusDays((shift * 5 * 7).toLong())
            (4 downTo 0).map { i ->
                val w = end.minusDays((i * 7).toLong())
                (w.year * 10000 + w.monthValue * 100 + w.dayOfMonth) to MD.format(w)
            }
        }
        KpiPeriod.YEAR -> {
            (11 downTo 0).map { i ->
                val m = LocalDate.of(today.year, 1, 1).plusMonths((today.monthValue - 1 - shift * 12 - i).toLong())
                (m.year * 100 + m.monthValue) to MON.format(m)
            }
        }
        KpiPeriod.ALL -> emptyList()
    }

    /**
     * Series (unique people per bucket, current vs preceding window) + the underlying events.
     * [datesOf] yields the dates a member is counted on for this metric.
     */
    fun metricData(
        rows: List<Member>,
        datesOf: (Member) -> List<LocalDate>,
        period: KpiPeriod,
        today: LocalDate = LocalDate.now(),
    ): KpiMetric {
        // Collect (member,date) up front so ALL can choose its granularity from the span.
        val pairs = ArrayList<Pair<Member, LocalDate>>()
        for (m in rows) for (dt in datesOf(m)) pairs.add(m to dt)

        var allByYear = false
        if (period == KpiPeriod.ALL && pairs.isNotEmpty()) {
            val earliest = pairs.minOf { it.second }
            val months = (today.year - earliest.year) * 12 + (today.monthValue - earliest.monthValue)
            allByYear = months > 36
        }

        val sets = HashMap<Int, MutableSet<String>>() // bucketKey -> unique person ids
        val raw = ArrayList<Triple<Member, LocalDate, Int>>()
        for ((m, dt) in pairs) {
            val id = (m.personUuid ?: m.name ?: System.identityHashCode(m).toString())
            val key = bucketKey(dt, period, allByYear)
            sets.getOrPut(key) { HashSet() }.add(id)
            raw.add(Triple(m, dt, key))
        }

        val cur: List<Pair<Int, String>>
        val prev: List<Pair<Int, String>>
        if (period == KpiPeriod.ALL) {
            if (raw.isEmpty()) return KpiMetric(KpiSeries(emptyList(), emptyList(), emptyList()), emptyList())
            val earliest = raw.minOf { it.second }
            val list = ArrayList<Pair<Int, String>>()
            if (allByYear) {
                for (y in earliest.year..today.year) list.add(y to y.toString())
            } else {
                var y = earliest.year
                var mo = earliest.monthValue
                while (y < today.year || (y == today.year && mo <= today.monthValue)) {
                    val d = LocalDate.of(y, mo, 1)
                    val lbl = if (y == today.year) MON.format(d) else MON_YY.format(d)
                    list.add((y * 100 + mo) to lbl)
                    mo++
                    if (mo > 12) { mo = 1; y++ }
                }
            }
            cur = list
            prev = emptyList()
        } else {
            cur = windowBuckets(period, today, 0)
            prev = windowBuckets(period, today, 1)
        }

        val idxOf = HashMap<Int, Int>()
        cur.forEachIndexed { i, b -> idxOf[b.first] = i }
        val series = KpiSeries(
            labels = cur.map { it.second },
            current = cur.map { (sets[it.first]?.size ?: 0).toDouble() },
            prev = prev.map { (sets[it.first]?.size ?: 0).toDouble() },
        )
        val events = raw.mapNotNull { (m, dt, key) -> idxOf[key]?.let { KpiEvent(m, dt, it) } }
        return KpiMetric(series, events)
    }

    /** Sundays this person was marked present at sacrament (details.sacrament[].attended==true). */
    fun attendedDates(m: Member): List<LocalDate> {
        val d = m.parsedDetails() ?: return emptyList()
        return d.sacrament.filter { it.attended }.mapNotNull { DateParse.parseMemberDate(it.date) }
    }

    /** The single date this person started being taught (details.firstLesson). */
    fun firstLessonDate(m: Member): List<LocalDate> {
        val fl = m.parsedDetails()?.firstLesson
        return DateParse.parseMemberDate(fl)?.let { listOf(it) } ?: emptyList()
    }

    /** Count of lessons (across [rows]) where a member was present for ≥1 principle. Mirrors `_lessonsWithMember`. */
    fun lessonsWithMember(rows: List<Member>): Int {
        var c = 0
        for (m in rows) {
            val lessons = m.parsedDetails()?.lessons ?: continue
            for (l in lessons) if (l.principles.any { it.memberPresent }) c++
        }
        return c
    }

    /** Average Golden Hour completion per unit, ranked high→low (n = baptized members in unit). */
    data class UnitPct(val unit: String, val pct: Double, val n: Int)

    fun unitCompletion(baptized: List<Member>, today: LocalDate = LocalDate.now()): List<UnitPct> {
        val byUnit = LinkedHashMap<String, MutableList<Member>>()
        for (m in baptized) byUnit.getOrPut(m.unitName ?: "—") { ArrayList() }.add(m)
        return byUnit.entries
            .map { UnitPct(it.key, Milestones.avgCompletion(it.value, today), it.value.size) }
            .sortedByDescending { it.pct }
    }

    /** Members who had ≥1 member-present lesson, with that count, ranked. Mirrors `_membersWithMemberLessons`. */
    data class MemberLessons(val member: Member, val count: Int)

    fun membersWithMemberLessons(rows: List<Member>): List<MemberLessons> {
        val out = ArrayList<MemberLessons>()
        for (m in rows) {
            val lessons = m.parsedDetails()?.lessons ?: continue
            var c = 0
            for (l in lessons) if (l.principles.any { it.memberPresent }) c++
            if (c > 0) out.add(MemberLessons(m, c))
        }
        return out.sortedByDescending { it.count }
    }

    /** The x-axis date range a Month/Year period spans (null for ALL). Mirrors `_periodRangeLabel`. */
    fun periodRangeLabel(period: KpiPeriod, today: LocalDate = LocalDate.now()): String? = when (period) {
        KpiPeriod.MONTH -> {
            val from = today.minusDays(35)
            "${MD_LONG.format(from)} – ${MD_Y.format(today)}"
        }
        KpiPeriod.YEAR -> {
            val from = LocalDate.of(today.year, 1, 1).plusMonths((today.monthValue - 1 - 11).toLong())
            "${M_Y.format(from)} – ${M_Y.format(today)}"
        }
        KpiPeriod.ALL -> null
    }

    /** (prior label, latest label) for the two big stats. Mirrors `_compareLabels`. */
    fun compareLabels(period: KpiPeriod): Pair<String, String> = when (period) {
        KpiPeriod.MONTH -> "Last month" to "This month"
        KpiPeriod.YEAR -> "Last year" to "This year"
        KpiPeriod.ALL -> "Prev. month" to "This month"
    }
}
