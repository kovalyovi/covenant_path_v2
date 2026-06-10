package org.membercovenantpath.viewer.logic

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AccountBalance
import androidx.compose.material.icons.filled.SupportAgent
import androidx.compose.material.icons.outlined.Badge
import androidx.compose.material.icons.outlined.Handshake
import androidx.compose.material.icons.outlined.MenuBook
import androidx.compose.material.icons.outlined.MilitaryTech
import androidx.compose.material.icons.outlined.VolunteerActivism
import androidx.compose.material.icons.outlined.WorkspacePremium
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import org.membercovenantpath.viewer.model.Member
import org.membercovenantpath.viewer.model.parsedDetails
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
        // Temple Ordinances and Experiences: genealogy + proxy baptisms, both from the year someone
        // turns 12 (limited-use recommend age — same by-year rule as calling/Aaronic).
        Milestone(
            label = "Family name prepared", abbr = "FN",
            icon = Icons.Outlined.MenuBook, color = MilestoneColors.FamilyName, // brown · 12+
            complete = { familyNameValue(it) == "Yes" },
            eligible = { m, today -> turnsAtLeast(m, 12, today) },
        ),
        Milestone(
            label = "First temple visit", abbr = "FT",
            icon = Icons.Filled.AccountBalance, color = MilestoneColors.FirstTempleVisit, // teal · 12+
            complete = { firstTempleVisitValue(it) == "Yes" },
            eligible = { m, today -> turnsAtLeast(m, 12, today) },
        ),
    )

    // ---- Temple Ordinances and Experiences (family name + first temple visit), mirrors web
    // milestones.ts `templeExperienceValue` / `templeExperienceDisplay`. ------------------------

    /**
     * Effective Yes/No for a temple-experience field. The flat column (filled by the daily sync)
     * wins; a row not yet re-synced falls back to `details.templeExperiences` — the same LCR
     * commitments, scraped earlier. Returns the raw flat value (sentinel/empty) when neither knows.
     */
    private fun templeExperienceValue(m: Member, flat: String?, needle: String): String {
        val v = flat ?: ""
        if (v == "Yes" || v == "No" || v == "N/A") return v
        val match = m.parsedDetails()?.templeExperiences
            ?.firstOrNull { (it.name ?: "").lowercase().contains(needle) }
        if (match != null) return if (match.done) "Yes" else "No"
        return v
    }

    /** Genealogy: the "Prepare a Family Name for the Temple" commitment. */
    fun familyNameValue(m: Member): String =
        templeExperienceValue(m, m.familyNamePrepared, "family name")

    /** First temple visit: the "Perform Baptisms for Deceased Ancestors" commitment. */
    fun firstTempleVisitValue(m: Member): String =
        templeExperienceValue(m, m.firstTempleVisit, "baptisms for deceased")

    /** Family name + first temple visit start at the limited-use recommend age (12, by-year rule). */
    fun templeExperienceEligible(m: Member, today: LocalDate = LocalDate.now()) =
        turnsAtLeast(m, 12, today)

    /**
     * Display: same N/A-for-ineligible gate as endowment (an under-12 can't do proxy baptisms yet,
     * so a raw "No" misleads); a real "Yes" is always kept.
     */
    fun familyNameDisplay(m: Member, today: LocalDate = LocalDate.now()): String {
        val v = familyNameValue(m)
        if (v == "Yes") return "Yes"
        return if (templeExperienceEligible(m, today)) v else "N/A"
    }

    fun firstTempleVisitDisplay(m: Member, today: LocalDate = LocalDate.now()): String {
        val v = firstTempleVisitValue(m)
        if (v == "Yes") return "Yes"
        return if (templeExperienceEligible(m, today)) v else "N/A"
    }

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

    // Per-field eligibility for the member-detail view (mirrors web milestones.ts so every surface
    // hides the same rows: no priesthood for women, no calling for a child, …).
    fun callingEligible(m: Member, today: LocalDate = LocalDate.now()) = turnsAtLeast(m, 12, today)
    fun ministeringAssignmentEligible(m: Member, today: LocalDate = LocalDate.now()) = turnsAtLeast(m, 14, today)
    fun aaronicEligible(m: Member, today: LocalDate = LocalDate.now()) = male(m) && turnsAtLeast(m, 12, today)
    fun melchizedekEligible(m: Member, today: LocalDate = LocalDate.now()) =
        male(m) && ageNowAtLeast(m, 18, today) && memberOneYearPlus(m, today)

    /** Priesthood section applies to males old enough for the Aaronic priesthood (12+). */
    fun priesthoodEligible(m: Member, today: LocalDate = LocalDate.now()) = male(m) && turnsAtLeast(m, 12, today)

    /** Temple recommend (incl. limited-use) and a patriarchal blessing both start around age 12. */
    fun templeRecommendEligible(m: Member, today: LocalDate = LocalDate.now()) = turnsAtLeast(m, 12, today)
    fun patriarchalEligible(m: Member, today: LocalDate = LocalDate.now()) = turnsAtLeast(m, 12, today)

    /** Endowment eligibility: an adult (18+) who's been a member ~1 year (same gate as the report). */
    fun endowmentEligible(m: Member, today: LocalDate = LocalDate.now()) =
        ageNowAtLeast(m, 18, today) && memberOneYearPlus(m, today)

    /**
     * Endowment (living_ordinance) display: "N/A" for the not-yet-eligible (a raw "No" misleads — they
     * can't be endowed yet); a real "Yes" is always kept. Same gate as the report + web.
     */
    fun endowmentDisplay(m: Member, today: LocalDate = LocalDate.now()): String {
        val v = m.livingOrdinance ?: ""
        if (v == "Yes") return "Yes"
        return if (endowmentEligible(m, today)) v else "N/A"
    }

    /**
     * Fraction 0..1 of this member's APPLICABLE milestones that are complete — drives the detail
     * completion ring (full + green at 1.0). Friends + Has-ministers apply to everyone, so ≥1 applies.
     */
    fun completionOf(m: Member, today: LocalDate = LocalDate.now()): Double {
        val applicable = forMember(m, today)
        if (applicable.isEmpty()) return 0.0
        return applicable.count { it.complete(m) }.toDouble() / applicable.size
    }

    /** Display age (e.g. "35 yrs"), or null when unknown/negative — for the detail header. */
    fun ageLabel(m: Member, today: LocalDate = LocalDate.now()): String? {
        val a = DateParse.ageNow(m.birthDate, today) ?: return null
        return if (a >= 0) "$a yrs" else null
    }

    /** Numeric age in years (for the table column's display + numeric sort), or null when unknown. */
    fun ageYears(m: Member, today: LocalDate = LocalDate.now()): Int? {
        val a = DateParse.ageNow(m.birthDate, today) ?: return null
        return if (a >= 0) a else null
    }

    /**
     * The Needs view tracks the 6 Golden Hour milestones PLUS the longer-horizon covenants we also
     * record (temple recommend, endowment, patriarchal blessing) — so leaders see everyone eligible-
     * but-missing each. [all] stays the integration-only completion basis; this is the superset.
     */
    val needsCategories: List<Milestone> = all + listOf(
        Milestone(
            label = "Temple Recommend", abbr = "TR",
            icon = Icons.Outlined.WorkspacePremium, color = Color(0xFF5E35B1),
            complete = { it.templeRecommend == "Active" },
            eligible = { m, today -> templeRecommendEligible(m, today) },
        ),
        Milestone(
            label = "Endowment", abbr = "EN",
            icon = Icons.Outlined.MilitaryTech, color = Color(0xFF00695C),
            complete = { it.livingOrdinance == "Yes" },
            eligible = { m, today -> endowmentEligible(m, today) },
        ),
        Milestone(
            label = "Patriarchal Blessing", abbr = "PB",
            icon = Icons.Outlined.Badge, color = Color(0xFFAD1457),
            complete = { it.patriarchalBlessing == "Yes" },
            eligible = { m, today -> patriarchalEligible(m, today) },
        ),
    )
}
