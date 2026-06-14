package org.membercovenantpath.viewer.logic

/**
 * Leadership / staffing gap rule (#12). Given a unit's roster of held callings (from the Member Tools
 * bulk payload, stored on `units.staffing`), determine which REQUIRED positions are filled and which
 * are gaps — "is there a ward mission leader? at least 2 ward missionaries? an EQ president? an RS
 * president?". Pure → a 1:1 mirror of the web `apps/web/src/logic/staffing.ts`. The position strings
 * are the LCR calling names.
 */

/** One held calling on a unit's roster. */
data class StaffingMember(
    val position: String,
    val person: String? = null,
    val personUuid: String? = null,
    val setApart: Boolean? = null,
)

/** Per-required-role fill status for a unit — [ok] when at least [min] are serving. */
data class RoleStatus(
    val key: String,
    val label: String,
    val have: Int,
    val min: Int,
    val ok: Boolean,
    val holders: List<String>, // names serving in this role (may be empty when unknown)
)

object Staffing {

    private data class RequiredRole(
        val key: String,
        val label: String,
        val min: Int,
        val match: (String) -> Boolean,
    )

    private fun matches(s: String, pattern: String): Boolean =
        Regex(pattern, RegexOption.IGNORE_CASE).containsMatchIn(s)

    /**
     * The roster every unit is expected to have for new-member success to be trackable (#12). This is
     * the single definition the gap check + the UI read — extend here as leaders ask for more.
     */
    private val REQUIRED_ROLES = listOf(
        RequiredRole("wml", "Ward mission leader", 1) {
            matches(it, "(ward|branch) mission leader") && !matches(it, "assistant|asst")
        },
        RequiredRole("ward_missionaries", "Ward missionaries", 2) {
            matches(it, "(ward|branch) missionary")
        },
        RequiredRole("eq_pres", "Elders Quorum president", 1) {
            matches(it, "elders quorum president") && !matches(it, "counselor|assistant|secretary|clerk")
        },
        RequiredRole("rs_pres", "Relief Society president", 1) {
            matches(it, "relief society president") && !matches(it, "counselor|assistant|secretary|clerk")
        },
    )

    /** Per-required-role fill status for a unit's roster — `ok` when at least `min` are serving. */
    fun gaps(roster: List<StaffingMember>): List<RoleStatus> = REQUIRED_ROLES.map { role ->
        val held = roster.filter { role.match(it.position) }
        val holders = held.mapNotNull { m -> m.person?.takeIf { it.isNotBlank() } }
        RoleStatus(role.key, role.label, held.size, role.min, held.size >= role.min, holders)
    }

    /** Count of unmet required roles for a unit (0 = fully staffed for the tracked positions). */
    fun gapCount(roster: List<StaffingMember>): Int = gaps(roster).count { !it.ok }
}
