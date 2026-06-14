package org.membercovenantpath.viewer.logic

/**
 * The CLIENT DISPLAY CONTRACT for any covenant-path field value, applied everywhere a field is shown
 * (table cells, person cards, detail sections). Ported 1:1 from the web's
 * `apps/web/src/logic/fieldDisplay.ts` + the `isSentinel`/`isAdminSentinel` recognizers in
 * `apps/web/src/lib/member.ts`.
 *
 * Three outcomes for a field value:
 *   - a REAL value (Yes/No/Active/a date/…)  -> status [VALUE] -> show it verbatim.
 *   - "N/A"                                   -> status [NA]    -> NOT ELIGIBLE; show quietly as "N/A"
 *                                                                 (or OMIT in Golden Hour). NEVER a warning.
 *   - the "needs-profile-api" sentinel, a "blocked: …" sentinel, OR null/empty
 *                                             -> status [ISSUE] -> a DATA ISSUE (we should have it but
 *                                                                 don't); show a warning indicator,
 *                                                                 NEVER the raw sentinel string.
 *
 * Critically — per the user's rule — the sentinel AND null/empty are treated THE SAME: both are a
 * data issue (a warning). An admin MAY see the raw sentinel string for diagnosis; a regular leader
 * never does.
 */
object FieldDisplay {

    /** The backend's internal sentinels (mirror covenant_path/report.py + backend/db.py _SENTINELS).
     *  These are TECHY/internal placeholder strings written when a field couldn't be fetched this run
     *  — only ADMINS should ever see the raw value; leaders get a warning instead. */
    const val NEEDS_PROFILE = "needs-profile-api"
    const val BLOCKED_PREFIX = "blocked" // e.g. "blocked: insufficient calling access"

    /** True when a value is one of the backend's internal sentinels (not real member data). */
    fun isSentinel(v: String?): Boolean {
        val s = v ?: ""
        return s == NEEDS_PROFILE || s.startsWith(BLOCKED_PREFIX)
    }

    /** Alias of [isSentinel] for the field-display contract — names the case where there's a raw,
     *  TECHY sentinel string an admin may be shown for diagnosis (vs a plain empty/missing value,
     *  which is a data issue too but carries no string to surface). */
    fun isAdminSentinel(v: String?): Boolean = isSentinel(v)

    /** A milestone/field value that means "doesn't apply to this person" (priesthood for a woman,
     *  patriarchal blessing for a young child, …). N/A is NOT the same as a data issue. Mirrors
     *  milestones.ts `isNA`. */
    fun isNA(v: String?): Boolean = (v ?: "").trim().uppercase() == "N/A"

    enum class Status { VALUE, NA, ISSUE }

    /**
     * Result of classifying a field value.
     *  - [text]: what to render — the real value, the literal "N/A", or "" for a data issue (the
     *    caller shows a warning indicator instead of text). For an admin a data-issue value keeps the
     *    raw sentinel so they can diagnose it; a leader never sees the techy string.
     *  - [warn]: true only for [Status.ISSUE] — the caller renders a warning indicator.
     */
    data class Result(val status: Status, val text: String, val warn: Boolean)

    /**
     * Classify a field value into the display contract above.
     *  - [isAdmin] only affects a data ISSUE: an admin sees the raw sentinel as the text (still
     *    warn=true) so they can diagnose "needs-profile-api"/"blocked: …"; a leader sees empty text
     *    + the warning only.
     */
    fun classify(v: String?, isAdmin: Boolean = false): Result {
        // N/A first — "not eligible" is a quiet, legitimate state, never a warning.
        if (isNA(v)) return Result(Status.NA, "N/A", warn = false)
        val s = (v ?: "").trim()
        // The backend sentinel OR an empty/missing value are BOTH a data issue (treated the same).
        if (s.isEmpty() || isSentinel(s)) {
            // Admins keep the raw sentinel string for diagnosis (only when it IS a sentinel — an
            // empty value has nothing techy to show); leaders never see it.
            val adminText = if (isAdmin && isAdminSentinel(s)) s else ""
            return Result(Status.ISSUE, adminText, warn = true)
        }
        return Result(Status.VALUE, s, warn = false)
    }

    /** Convenience: is this value a data issue (sentinel OR null/empty, but NOT N/A)? */
    fun isDataIssue(v: String?): Boolean = classify(v).status == Status.ISSUE
}
