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
enum class KpiPeriod { MONTH, YTD, YEAR, ALL, CUSTOM }

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

/** #1/#2: window for the Baptisms-by-month stat (year-to-date / trailing 12 / 24 / all-time). */
enum class BaptismWindow { YTD, M12, M24, ALL }

/** #1/#2: monthly baptism counts over a window + the best month (named) + total in-window. */
data class BaptismsByMonth(
    val labels: List<String>,
    val counts: List<Double>,
    val events: List<KpiEvent>,
    val bestLabel: String?,
    val bestCount: Int,
    val total: Int,
)

object Kpis {

    private val MD = DateTimeFormatter.ofPattern("M/d", Locale.US)   // "2/6"
    private val MON = DateTimeFormatter.ofPattern("MMM", Locale.US)  // "Feb"
    private val MD_LONG = DateTimeFormatter.ofPattern("MMM d", Locale.US)
    private val MD_Y = DateTimeFormatter.ofPattern("MMM d, yyyy", Locale.US)
    private val M_Y = DateTimeFormatter.ofPattern("MMM yyyy", Locale.US)
    private val MON_YY = DateTimeFormatter.ofPattern("MMM ''yy", Locale.US) // "Feb '25"
    private val MMMM_Y = DateTimeFormatter.ofPattern("MMMM yyyy", Locale.US) // "March 2026" (best month)

    private fun weekStart(d: LocalDate): LocalDate = d.minusDays((d.dayOfWeek.value - 1).toLong()) // Monday

    /** Bucket key (stable, sortable int) for an event date under [p] — must match windowBuckets. */
    private fun bucketKey(dt: LocalDate, p: KpiPeriod, allByYear: Boolean): Int = when (p) {
        KpiPeriod.MONTH -> {
            val w = weekStart(dt)
            w.year * 10000 + w.monthValue * 100 + w.dayOfMonth
        }
        KpiPeriod.YTD, KpiPeriod.YEAR, KpiPeriod.CUSTOM -> dt.year * 100 + dt.monthValue
        KpiPeriod.ALL -> if (allByYear) dt.year else dt.year * 100 + dt.monthValue
    }

    /**
     * Ordered (key,label) buckets of the window ending [today], shifted back [shift] windows
     * (shift=1 → the preceding equal span). ALL is data-driven (handled in [metricData]) → empty here.
     */
    private fun windowBuckets(
        p: KpiPeriod,
        today: LocalDate,
        shift: Int,
        custom: Pair<LocalDate, LocalDate>? = null,
    ): List<Pair<Int, String>> = when (p) {
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
        KpiPeriod.YTD -> {
            // Calendar year-to-date: Jan..current month of (this year − shift). shift=1 → last year's
            // same Jan..now span, position-aligned, so "Compare to previous" is year-over-year.
            val y = today.year - shift
            (1..today.monthValue).map { m ->
                (y * 100 + m) to MON.format(LocalDate.of(y, m, 1))
            }
        }
        KpiPeriod.CUSTOM -> {
            // #7: monthly buckets from start..end, shifted back `shift` YEARS so the compare overlay
            // is the same calendar range one year earlier (year-over-year).
            if (custom == null) emptyList()
            else {
                val out = ArrayList<Pair<Int, String>>()
                var y = custom.first.year - shift
                var mo = custom.first.monthValue
                val endY = custom.second.year - shift
                val endMo = custom.second.monthValue
                while (y < endY || (y == endY && mo <= endMo)) {
                    out.add((y * 100 + mo) to MON.format(LocalDate.of(y, mo, 1)))
                    if (++mo > 12) { mo = 1; y++ }
                }
                out
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
        customRange: Pair<LocalDate, LocalDate>? = null,
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
            cur = windowBuckets(period, today, 0, customRange)
            prev = windowBuckets(period, today, 1, customRange)
        }

        val idxOf = HashMap<Int, Int>()
        cur.forEachIndexed { i, b -> idxOf[b.first] = i }
        val series = KpiSeries(
            labels = cur.map { it.second },
            current = cur.map { (sets[it.first]?.size ?: 0).toDouble() },
            prev = prev.map { (sets[it.first]?.size ?: 0).toDouble() },
        )
        val events = raw.mapNotNull { (m, dt, key) -> idxOf[key]?.let { KpiEvent(m, dt, it) } }
        return trimEmptyBuckets(series, events)
    }

    /**
     * N9: trim leading AND trailing all-zero buckets so a short/sparse history shows just its data
     * span (e.g. 5 weeks, or 2 months → 2 points) instead of a long run of padded 0s. Interior gaps
     * stay; all-zero (no data) → empty series so the chart shows its empty state. Mirrors
     * `_trimEmptyBuckets` in dashboard_common.dart exactly (prev overlay cut to the same indices).
     */
    private fun trimEmptyBuckets(s: KpiSeries, events: List<KpiEvent>): KpiMetric {
        val first = s.current.indexOfFirst { it > 0 }
        if (first < 0) return KpiMetric(KpiSeries(emptyList(), emptyList(), emptyList()), emptyList())
        val last = s.current.indexOfLast { it > 0 }
        if (first == 0 && last == s.current.size - 1) return KpiMetric(s, events)
        fun cut(xs: List<Double>): List<Double> =
            if (first < xs.size) xs.subList(first, (last + 1).coerceIn(first, xs.size)).toList() else emptyList()
        return KpiMetric(
            KpiSeries(
                labels = s.labels.subList(first, last + 1).toList(),
                current = s.current.subList(first, last + 1).toList(),
                prev = cut(s.prev),
            ),
            events.filter { it.bucket in first..last }.map { KpiEvent(it.member, it.date, it.bucket - first) },
        )
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
    fun periodRangeLabel(
        period: KpiPeriod,
        today: LocalDate = LocalDate.now(),
        custom: Pair<LocalDate, LocalDate>? = null,
    ): String? = when (period) {
        KpiPeriod.MONTH -> {
            val from = today.minusDays(35)
            "${MD_LONG.format(from)} – ${MD_Y.format(today)}"
        }
        KpiPeriod.YEAR -> {
            val from = LocalDate.of(today.year, 1, 1).plusMonths((today.monthValue - 1 - 11).toLong())
            "${M_Y.format(from)} – ${M_Y.format(today)}"
        }
        KpiPeriod.YTD -> {
            val from = LocalDate.of(today.year, 1, 1) // Jan 1 → today
            "${MD_LONG.format(from)} – ${MD_Y.format(today)}"
        }
        KpiPeriod.CUSTOM -> custom?.let { "${MD_Y.format(it.first)} – ${MD_Y.format(it.second)}" }
        KpiPeriod.ALL -> null
    }

    /** (prior label, latest label) for the two big stats. Mirrors `_compareLabels`. */
    fun compareLabels(period: KpiPeriod): Pair<String, String> = when (period) {
        KpiPeriod.MONTH -> "Last month" to "This month"
        KpiPeriod.YTD -> "Last year" to "This year" // YTD totals: this year vs same period last year
        KpiPeriod.YEAR -> "Last year" to "This year"
        KpiPeriod.CUSTOM -> "Last year" to "This year" // same range, one year earlier
        KpiPeriod.ALL -> "Prev. month" to "This month"
    }

    /**
     * #1/#2: baptized-convert cohort counted by baptism MONTH over [window], with the best month
     * named. Mirrors `_baptismsByMonth` in dashboard_common.dart. "Baptised and confirmed" = the
     * convert cohort, counted by baptism date (confirmation follows within days).
     */
    fun baptismsByMonth(
        baptized: List<Member>,
        window: BaptismWindow,
        today: LocalDate = LocalDate.now(),
    ): BaptismsByMonth {
        val start: LocalDate? = when (window) {
            BaptismWindow.YTD -> LocalDate.of(today.year, 1, 1)
            BaptismWindow.M12 -> LocalDate.of(today.year, 1, 1).plusMonths((today.monthValue - 1 - 11).toLong())
            BaptismWindow.M24 -> LocalDate.of(today.year, 1, 1).plusMonths((today.monthValue - 1 - 23).toLong())
            BaptismWindow.ALL -> null
        }
        val pairs = ArrayList<Pair<Member, LocalDate>>()
        for (m in baptized) {
            val dt = DateParse.parseMemberDate(m.baptismDate) ?: continue
            if (dt.isAfter(today)) continue
            if (start != null && dt.isBefore(start)) continue
            pairs.add(m to dt)
        }
        val rangeStart: LocalDate = start
            ?: (pairs.minOfOrNull { it.second }?.withDayOfMonth(1) ?: LocalDate.of(today.year, today.monthValue, 1))
        val labels = ArrayList<String>()
        val keys = ArrayList<Int>()
        var y = rangeStart.year
        var mo = rangeStart.monthValue
        while (y < today.year || (y == today.year && mo <= today.monthValue)) {
            keys.add(y * 100 + mo)
            val d = LocalDate.of(y, mo, 1)
            labels.add(if (y == today.year) MON.format(d) else MON_YY.format(d))
            mo++
            if (mo > 12) { mo = 1; y++ }
        }
        val idxOf = HashMap<Int, Int>()
        keys.forEachIndexed { i, k -> idxOf[k] = i }
        val counts = DoubleArray(keys.size)
        val events = ArrayList<KpiEvent>()
        for ((m, dt) in pairs) {
            val i = idxOf[dt.year * 100 + dt.monthValue] ?: continue
            counts[i] += 1 // a convert is baptized once → counted once, in their baptism month
            events.add(KpiEvent(m, dt, i))
        }
        var bi = -1
        var bc = 0.0
        for (i in counts.indices) if (counts[i] > bc) { bc = counts[i]; bi = i }
        val bestLabel = if (bi >= 0) MMMM_Y.format(LocalDate.of(keys[bi] / 100, keys[bi] % 100, 1)) else null
        val total = counts.sum().toInt()
        // N9: trim leading & trailing empty months — show just the data span, not padded 0s. (Total &
        // best are over the full in-window range, but trimmed buckets are all 0, so they're unchanged.)
        val first = counts.indexOfFirst { it > 0 }
        if (first < 0) return BaptismsByMonth(emptyList(), emptyList(), emptyList(), null, 0, 0)
        val last = counts.indexOfLast { it > 0 }
        return BaptismsByMonth(
            labels.subList(first, last + 1).toList(),
            counts.toList().subList(first, last + 1).toList(),
            events.filter { it.bucket in first..last }.map { KpiEvent(it.member, it.date, it.bucket - first) },
            bestLabel,
            bc.toInt(),
            total,
        )
    }
}
