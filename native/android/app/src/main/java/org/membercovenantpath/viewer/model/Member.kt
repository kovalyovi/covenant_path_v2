package org.membercovenantpath.viewer.model

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonObject

/**
 * One tracked person, mirroring the `members` table columns the Flutter dashboard selects
 * (see SPEC.md "Select string" / dashboard_page.dart `_columns`). RLS returns only rows the
 * signed-in user may see — the app does NO filtering of its own.
 *
 * Yes/No status fields are kept as raw strings ("Yes" / "No" / "N/A" / sentinel) because the
 * milestone logic compares against the literal "Yes" exactly like the Flutter app does, and
 * because sentinels ("needs-profile-api", "blocked: ...") mean "unknown", not "No".
 *
 * `@SerialName` values match the snake_case DB columns 1:1.
 */
@Serializable
data class Member(
    @SerialName("person_uuid") val personUuid: String? = null,
    @SerialName("stake_id") val stakeId: String? = null,
    @SerialName("unit_id") val unitId: String? = null,
    @SerialName("name") val name: String? = null,
    @SerialName("unit_name") val unitName: String? = null,
    @SerialName("kind") val kind: String? = null, // 'new_member' | 'investigator' | 'returning'
    @SerialName("baptism_date") val baptismDate: String? = null,
    @SerialName("baptism_goal_date") val baptismGoalDate: String? = null,
    @SerialName("birth_date") val birthDate: String? = null,
    @SerialName("membership_duration") val membershipDuration: String? = null,
    @SerialName("sex") val sex: String? = null, // 'M' / 'F'

    // Yes/No status fields.
    @SerialName("friends") val friends: String? = null,
    @SerialName("friends_count") val friendsCount: Int? = null,
    @SerialName("aaronic_priesthood") val aaronicPriesthood: String? = null,
    @SerialName("melchizedek_priesthood") val melchizedekPriesthood: String? = null,
    @SerialName("calling") val calling: String? = null,
    @SerialName("ministering_brothers_sisters") val ministeringBrothersSisters: String? = null,
    @SerialName("ministering_assignment") val ministeringAssignment: String? = null,
    @SerialName("temple_recommend") val templeRecommend: String? = null, // Active / Expired / No
    @SerialName("patriarchal_blessing") val patriarchalBlessing: String? = null,
    @SerialName("living_ordinance") val livingOrdinance: String? = null,

    // Rich detail subtree for the person-detail page (may be partial / null).
    @SerialName("details") val details: JsonObject? = null,
    @SerialName("photo_url") val photoUrl: String? = null,
) {
    val isInvestigator: Boolean get() = kind == "investigator"

    /** Raw value for a milestone "yes/no" key, by the same DB column name the milestone uses. */
    fun status(field: String): String? = when (field) {
        "friends" -> friends
        "aaronic_priesthood" -> aaronicPriesthood
        "melchizedek_priesthood" -> melchizedekPriesthood
        "calling" -> calling
        "ministering_brothers_sisters" -> ministeringBrothersSisters
        "ministering_assignment" -> ministeringAssignment
        "temple_recommend" -> templeRecommend
        "patriarchal_blessing" -> patriarchalBlessing
        "living_ordinance" -> livingOrdinance
        else -> null
    }
}
