package org.membercovenantpath.viewer.logic

import java.time.LocalDate
import java.time.Period
import java.time.temporal.ChronoUnit
import kotlin.math.floor

/**
 * Date parsing + tenure math, ported 1:1 from the Flutter app
 * (golden_hour.dart `_dateOf`/`_yearOf`/`_ageNow`/`monthsDaysAgo`, dashboard_common.dart
 * `parseMemberDate`). Pure and unit-testable — no Android dependencies.
 *
 * Must handle: ISO `2026-02-06`, `6 Feb 2026`, `2/6/2026`, and the sentinel strings
 * (`N/A`, `needs-profile-api`, `blocked: ...`) which all mean "null/unknown".
 */
object DateParse {

    private val MONTHS = listOf(
        "jan", "feb", "mar", "apr", "may", "jun",
        "jul", "aug", "sep", "oct", "nov", "dec",
    )

    private val DMY = Regex("""^(\d{1,2})\s+([A-Za-z]{3,})\s+(\d{4})$""")
    private val MDY = Regex("""^(\d{1,2})/(\d{1,2})/(\d{2,4})$""")
    private val ISO = Regex("""^(\d{4})-(\d{1,2})-(\d{1,2})""") // leading date of an ISO timestamp
    private val FOUR_DIGITS = Regex("""(\d{4})""")
    private val YEAR_TENURE = Regex("""(\d+)\s*year""")

    /** True for empty / N/A / needs-profile-api / blocked sentinels. */
    private fun isSentinel(s: String): Boolean =
        s.isEmpty() || s == "N/A" || s == "needs-profile-api" || s.startsWith("blocked")

    /**
     * Parse any of the supported member-date formats, else null.
     * Mirrors dashboard_common.parseMemberDate (the superset that also accepts m/d/y).
     */
    fun parseMemberDate(value: Any?): LocalDate? {
        val s = value?.toString()?.trim() ?: return null
        if (isSentinel(s)) return null

        ISO.find(s)?.let { m ->
            runCatching {
                return LocalDate.of(
                    m.groupValues[1].toInt(),
                    m.groupValues[2].toInt(),
                    m.groupValues[3].toInt(),
                )
            }
        }
        DMY.matchEntire(s)?.let { m ->
            val mo = MONTHS.indexOf(m.groupValues[2].lowercase().take(3))
            if (mo >= 0) runCatching {
                return LocalDate.of(m.groupValues[3].toInt(), mo + 1, m.groupValues[1].toInt())
            }
        }
        MDY.matchEntire(s)?.let { m ->
            var y = m.groupValues[3].toInt()
            if (y < 100) y += 2000
            runCatching {
                return LocalDate.of(y, m.groupValues[1].toInt(), m.groupValues[2].toInt())
            }
        }
        return null
    }

    /** First 4-digit run as an Int (year), else null. Mirrors `_yearOf`. */
    fun yearOf(value: Any?): Int? =
        FOUR_DIGITS.find(value?.toString() ?: "")?.groupValues?.get(1)?.toIntOrNull()

    /**
     * Actual current age from a full birth date when present, else by-year.
     * Mirrors `_ageNow`. [today] is injectable for tests.
     */
    fun ageNow(birth: Any?, today: LocalDate = LocalDate.now()): Int? {
        val d = parseMemberDate(birth)
        if (d != null) return Period.between(d, today).years
        val by = yearOf(birth) ?: return null
        return today.year - by
    }

    /** "N yrs" or null (when unknown / negative). Mirrors `ageOf`. */
    fun ageLabel(birth: Any?, today: LocalDate = LocalDate.now()): String? {
        val a = ageNow(birth, today)
        return if (a == null || a < 0) null else "$a yrs"
    }

    /**
     * Member for ≥1 year: baptism_date ≥365 days ago, OR membership_duration says "N year(s)"
     * with N≥1. Mirrors `_memberOneYearPlus`.
     */
    fun memberOneYearPlus(
        baptismDate: Any?,
        membershipDuration: Any?,
        today: LocalDate = LocalDate.now(),
    ): Boolean {
        parseMemberDate(baptismDate)?.let { b ->
            return ChronoUnit.DAYS.between(b, today) >= 365
        }
        val ym = YEAR_TENURE.find((membershipDuration?.toString() ?: "").lowercase())
        return (ym?.groupValues?.get(1)?.toIntOrNull() ?: 0) >= 1
    }

    /** Whole months since [date] (the floor of days/30.44). Used by org ownership. */
    fun monthsSince(date: LocalDate, today: LocalDate = LocalDate.now()): Int =
        floor(ChronoUnit.DAYS.between(date, today) / 30.44).toInt()

    /**
     * Compact elapsed time since a past date, e.g. "2 months 3 days". Empty for a future/unknown
     * date. Ported from `monthsDaysAgo` (calendar-aware month/day breakdown, not days/30).
     */
    fun monthsDaysAgo(d: LocalDate?, today: LocalDate = LocalDate.now()): String {
        if (d == null || d.isAfter(today)) return ""
        var months = (today.year - d.year) * 12 + today.monthValue - d.monthValue
        val days: Int
        if (today.dayOfMonth >= d.dayOfMonth) {
            days = today.dayOfMonth - d.dayOfMonth
        } else {
            months -= 1
            val daysInPrevMonth = today.minusMonths(1).lengthOfMonth()
            days = daysInPrevMonth - d.dayOfMonth + today.dayOfMonth
        }
        if (months < 0) return ""
        val parts = buildList {
            if (months > 0) add("$months month${if (months == 1) "" else "s"}")
            if (days > 0 || months == 0) add("$days day${if (days == 1) "" else "s"}")
        }
        return parts.joinToString(" ")
    }
}
