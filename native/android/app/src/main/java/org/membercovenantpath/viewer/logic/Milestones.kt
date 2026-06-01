package org.membercovenantpath.viewer.logic

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.SupportAgent
import androidx.compose.material.icons.outlined.Badge
import androidx.compose.material.icons.outlined.Handshake
import androidx.compose.material.icons.outlined.MilitaryTech
import androidx.compose.material.icons.outlined.VolunteerActivism
import androidx.compose.material.icons.outlined.WorkspacePremium
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import org.membercovenantpath.viewer.model.Member
import org.membercovenantpath.viewer.ui.theme.MilestoneColors
import java.time.LocalDate

/**
 * "Golden Hour" = a new member's first-year integration milestones, each gated to who it can
 * actually apply to (age / sex / tenure) so completion stats don't penalize the ineligible.
 *
 * Ported 1:1 from golden_hour.dart (`Milestone`, the `milestones` list, `_turnsAtLeast`,
 * `_memberOneYearPlus`, `_ageNowAtLeast`, `_male`, `milestonesFor`). The eligibility/completion
 * predicates take an injectable [today] so they're deterministic in tests.
 *
 * Baptism is intentionally NOT a milestone; longer-horizon ordinances live on the detail page.
 */
data class Milestone(
    val label: String,           // full name (detail + accessibility)
    val abbr: String,            // chip label (1-2 chars)
    val icon: ImageVector,       // category icon (Needs tabs, summaries)
    val color: Color,            // category identity color
    val complete: (Member) -> Boolean,
    val eligible: (Member, LocalDate) -> Boolean = { _, _ -> true }, // who this can apply to
) {
    fun eligible(m: Member, today: LocalDate = LocalDate.now()): Boolean = eligible.invoke(m, today)
}

object Milestones {

    private fun male(m: Member) = m.sex == "M"

    /**
     * "Turns at least [age] by the end of this calendar year" — the Church's by-year quorum/
     * advancement rule (an 11-year-old turning 12 this year counts). Unknown birth → not eligible.
     * Mirrors `_turnsAtLeast`.
     */
    private fun turnsAtLeast(m: Member, age: Int, today: LocalDate): Boolean {
        val by = DateParse.yearOf(m.birthDate) ?: return false
        return (today.year - by) >= age
    }

    /** Mirrors `_ageNowAtLeast`. */
    private fun ageNowAtLeast(m: Member, age: Int, today: LocalDate): Boolean {
        val a = DateParse.ageNow(m.birthDate, today) ?: return false
        return a >= age
    }

    private fun memberOneYearPlus(m: Member, today: LocalDate): Boolean =
        DateParse.memberOneYearPlus(m.baptismDate, m.membershipDuration, today)

    /** The canonical, ordered milestone list — exactly matches golden_hour.dart `milestones`. */
    val all: List<Milestone> = listOf(
        Milestone(
            label = "Friends", abbr = "F",
            icon = Icons.Outlined.Handshake, color = MilestoneColors.Friends, // pink · everyone
            complete = { it.friends == "Yes" },
        ),
        Milestone(
            label = "Calling", abbr = "C",
            icon = Icons.Outlined.Badge, color = MilestoneColors.Calling, // purple
            complete = { it.calling == "Yes" },
            eligible = { m, today -> turnsAtLeast(m, 12, today) },
        ),
        Milestone(
            label = "Has ministers", abbr = "M",
            icon = Icons.Filled.SupportAgent, color = MilestoneColors.HasMinisters, // cyan · everyone
            complete = { it.ministeringBrothersSisters == "Yes" },
        ),
        Milestone(
            label = "Ministering assignment", abbr = "MA",
            icon = Icons.Outlined.VolunteerActivism, color = MilestoneColors.MinisteringAssignment, // orange
            complete = { it.ministeringAssignment == "Yes" },
            eligible = { m, today -> turnsAtLeast(m, 14, today) }, // gives ministering: 14+
        ),
        Milestone(
            label = "Aaronic Priesthood", abbr = "AP",
            icon = Icons.Outlined.MilitaryTech, color = MilestoneColors.AaronicPriesthood, // blue
            complete = { it.aaronicPriesthood == "Yes" },
            eligible = { m, today -> male(m) && turnsAtLeast(m, 12, today) },
        ),
        Milestone(
            label = "Melchizedek Priesthood", abbr = "MP",
            icon = Icons.Outlined.WorkspacePremium, color = MilestoneColors.MelchizedekPriesthood, // green
            complete = { it.melchizedekPriesthood == "Yes" },
            eligible = { m, today ->
                male(m) && ageNowAtLeast(m, 18, today) && memberOneYearPlus(m, today)
            },
        ),
    )

    /** Milestones that can apply to [m] (eligible-only). Mirrors `milestonesFor`. */
    fun forMember(m: Member, today: LocalDate = LocalDate.now()): List<Milestone> =
        all.filter { it.eligible(m, today) }

    /**
     * Average Golden Hour completion across [members] (eligible-only per person; ineligible-for-all
     * are skipped). Mirrors `_avgCompletion`.
     */
    fun avgCompletion(members: List<Member>, today: LocalDate = LocalDate.now()): Double {
        if (members.isEmpty()) return 0.0
        var sum = 0.0
        for (m in members) {
            val applicable = forMember(m, today)
            if (applicable.isEmpty()) continue
            sum += applicable.count { it.complete(m) }.toDouble() / applicable.size
        }
        return sum / members.size
    }
}
