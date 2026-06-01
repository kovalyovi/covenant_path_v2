package org.membercovenantpath.viewer.logic

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Diversity1
import androidx.compose.material.icons.outlined.FilterAltOff
import androidx.compose.material.icons.outlined.Group
import androidx.compose.material.icons.outlined.Groups2
import androidx.compose.material.icons.outlined.HelpOutline
import androidx.compose.material.icons.outlined.VolunteerActivism
import androidx.compose.ui.graphics.vector.ImageVector
import org.membercovenantpath.viewer.model.Member
import org.membercovenantpath.viewer.ui.theme.OrgColors
import java.time.LocalDate

/**
 * Convert responsibility — the stake's hand-off policy (#23), ported 1:1 from golden_hour.dart.
 * ONE source of org ownership for filters + chips. First year after baptism → Missionaries/WML;
 * after a year → Elders Quorum (men) / Relief Society (women).
 */
enum class OrgBucket { WML, EQ, RS }

/** Label + short tag + icon + identity color for an org bucket (mirrors `orgInfo`). */
data class OrgInfo(
    val label: String,
    val short: String,
    val icon: ImageVector,
    val color: androidx.compose.ui.graphics.Color,
)

object Orgs {

    fun info(b: OrgBucket): OrgInfo = when (b) {
        OrgBucket.WML -> OrgInfo(
            label = "Missionaries / WML",
            short = "WML",
            icon = Icons.Outlined.VolunteerActivism,
            color = OrgColors.WML, // teal
        )
        OrgBucket.EQ -> OrgInfo(
            label = "Elders Quorum",
            short = "EQ",
            icon = Icons.Outlined.Groups2,
            color = OrgColors.EQ, // blue
        )
        OrgBucket.RS -> OrgInfo(
            label = "Relief Society",
            short = "RS",
            icon = Icons.Outlined.Diversity1,
            color = OrgColors.RS, // rose
        )
    }

    /**
     * Which org currently owns this convert's integration, or null when there's no baptism date.
     * <12 months → WML; ≥12 months → EQ (men) / RS (women). Mirrors `responsibleOrg`.
     */
    fun responsibleOrg(m: Member, today: LocalDate = LocalDate.now()): OrgBucket? {
        val b = DateParse.parseMemberDate(m.baptismDate) ?: return null
        val months = DateParse.monthsSince(b, today)
        if (months < 12) return OrgBucket.WML
        return if (m.sex == "M") OrgBucket.EQ else OrgBucket.RS
    }

    /** Responsibility chip data (label + icon + color), Unassigned when no baptism date. */
    data class Party(val label: String, val icon: ImageVector, val color: androidx.compose.ui.graphics.Color)

    fun responsibleParty(m: Member, today: LocalDate = LocalDate.now()): Party {
        val org = responsibleOrg(m, today)
            ?: return Party("Unassigned", Icons.Outlined.HelpOutline, OrgColors.Unassigned)
        val i = info(org)
        return Party(i.label, i.icon, i.color)
    }

    /** One-line explanation shown under the filter (mirrors `orgResponsibilityNote`). */
    fun responsibilityNote(b: OrgBucket): String = when (b) {
        OrgBucket.WML ->
            "First year after baptism: the full-time missionaries and the ward mission leader " +
                "watch over each new member's progress."
        OrgBucket.EQ ->
            "After the first year: the elders quorum presidency watches over each brother's " +
                "continued integration."
        OrgBucket.RS ->
            "After the first year: the Relief Society presidency watches over each sister's " +
                "continued integration."
    }

    val clearFiltersIcon: ImageVector = Icons.Outlined.FilterAltOff
    val genericGroupIcon: ImageVector = Icons.Outlined.Group
}
