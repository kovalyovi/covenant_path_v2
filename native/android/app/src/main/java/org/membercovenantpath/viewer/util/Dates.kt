package org.membercovenantpath.viewer.util

import java.time.LocalDate
import java.time.format.DateTimeFormatter
import java.time.format.TextStyle
import java.util.Locale

/**
 * Display formatters mirroring the Flutter app's intl `DateFormat` patterns. Kept in one place so
 * the timeline, lists, and detail page format dates identically.
 */
object Dates {
    private val MONTH_DAY_YEAR = DateTimeFormatter.ofPattern("MMMM d, yyyy", Locale.US) // "February 6, 2026"
    private val FULL_LONG = DateTimeFormatter.ofPattern("EEEE, MMMM d, yyyy", Locale.US) // "Friday, February 6, 2026"
    private val MONTH_DAY = DateTimeFormatter.ofPattern("MMM d", Locale.US)              // "Feb 6"
    private val MONTH_DAY_YEAR_SHORT = DateTimeFormatter.ofPattern("MMM d, yyyy", Locale.US)

    fun longMonthDayYear(d: LocalDate): String = d.format(MONTH_DAY_YEAR)
    fun fullLong(d: LocalDate?): String = d?.format(FULL_LONG) ?: ""
    fun monthDay(d: LocalDate): String = d.format(MONTH_DAY)
    fun monthDayYearShort(d: LocalDate): String = d.format(MONTH_DAY_YEAR_SHORT)

    /** Uppercased 3-letter month, e.g. "FEB" (timeline date block). */
    fun monthAbbrUpper(d: LocalDate): String =
        d.month.getDisplayName(TextStyle.SHORT, Locale.US).uppercase()

    /** 3-letter weekday, e.g. "Fri". */
    fun weekdayAbbr(d: LocalDate): String =
        d.dayOfWeek.getDisplayName(TextStyle.SHORT, Locale.US)
}
