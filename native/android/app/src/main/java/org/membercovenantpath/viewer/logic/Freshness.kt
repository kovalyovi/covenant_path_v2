package org.membercovenantpath.viewer.logic

import androidx.compose.ui.graphics.Color
import org.membercovenantpath.viewer.ui.theme.StatusColors
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.time.temporal.ChronoUnit
import java.util.Locale

/**
 * Data-freshness helpers, ported 1:1 from dashboard_common.dart (`_ago`, `_staleColor`) + the exact
 * local-time format the freshness dialog uses. Pure (injectable [now]) so it's unit-testable.
 */
object Freshness {

    /** Parse an ISO-8601 timestamp (with or without zone) to an [Instant], else null. */
    fun parseInstant(iso: String?): Instant? {
        val s = iso?.trim().orEmpty()
        if (s.isEmpty()) return null
        return runCatching { Instant.parse(s) }.getOrElse {
            // Bare "yyyy-MM-ddTHH:mm:ss" without zone → treat as UTC (matches DateTime.tryParse).
            runCatching { Instant.parse(s + "Z") }.getOrElse {
                runCatching {
                    java.time.LocalDateTime.parse(s).atZone(ZoneId.of("UTC")).toInstant()
                }.getOrNull()
            }
        }
    }

    /** "5m ago" / "3h ago" / "2d ago", mirroring `_ago`. Falls back to the raw string if unparseable. */
    fun ago(iso: String?, now: Instant = Instant.now()): String {
        val t = parseInstant(iso) ?: return iso ?: ""
        val mins = ChronoUnit.MINUTES.between(t, now)
        if (mins < 1) return "just now"
        if (mins < 60) return "${mins}m ago"
        val hours = ChronoUnit.HOURS.between(t, now)
        if (hours < 24) return "${hours}h ago"
        return "${ChronoUnit.DAYS.between(t, now)}d ago"
    }

    /** Human duration for a job's execution time (seconds → "45s", "2m 13s", "1h 4m"). Mirrors `_dur`. */
    fun dur(seconds: Any?): String {
        val s = when (seconds) {
            is Number -> seconds.toLong()
            is String -> seconds.toLongOrNull()
            else -> null
        } ?: return ""
        if (s < 0) return ""
        if (s < 60) return "${s}s"
        val m = s / 60; val rs = s % 60
        if (m < 60) return if (rs == 0L) "${m}m" else "${m}m ${rs}s"
        val h = m / 60; val rm = m % 60
        return if (rm == 0L) "${h}h" else "${h}h ${rm}m"
    }

    /**
     * Staleness color for a last-synced timestamp (#18): red after 2 weeks, amber after 2 days,
     * null (fresh / default) otherwise. Never-synced reads as red. Mirrors `_staleColor`.
     */
    fun staleColor(iso: String?, now: Instant = Instant.now()): Color? {
        val t = parseInstant(iso) ?: return StatusColors.NoRed
        val days = ChronoUnit.DAYS.between(t, now)
        return when {
            days >= 14 -> StatusColors.NoRed
            days >= 2 -> StatusColors.NextAmber
            else -> null
        }
    }

    private val EXACT = DateTimeFormatter.ofPattern("MMM d, yyyy · h:mm a", Locale.US)

    /** Exact local time, e.g. "Feb 6, 2026 · 7:00 AM" + zone — the freshness dialog / sync sheet. */
    fun exactLocal(iso: String?): String {
        val t = parseInstant(iso) ?: return iso ?: ""
        val z = t.atZone(ZoneId.systemDefault())
        return z.format(EXACT) + " " + z.zone.getDisplayName(java.time.format.TextStyle.SHORT, Locale.US)
    }
}
