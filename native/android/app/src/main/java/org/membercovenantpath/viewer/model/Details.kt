package org.membercovenantpath.viewer.model

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull

/**
 * Typed projection of the `members.details` jsonb subtree used by the person-detail page.
 * Everything is optional/nullable — `details` may be partial or absent (a row synced before the
 * schema change), in which case the detail page falls back to the flat [Member] fields.
 *
 * Field names mirror the camelCase keys the Flutter app reads in person_detail_page.dart.
 */
@Serializable
data class Details(
    @SerialName("memberSince") val memberSince: String? = null,
    @SerialName("firstLesson") val firstLesson: String? = null,
    // May be a number or a string in jsonb; raw element + tolerant [sacramentMissedCount] accessor.
    @SerialName("sacramentMissed") val sacramentMissed: JsonElement? = null,

    val friends: List<FriendRef> = emptyList(),
    val ministeringBrothers: List<String> = emptyList(),
    val ministeringSisters: List<String> = emptyList(),
    val sacrament: List<SacramentEntry> = emptyList(),
    val lessons: List<Lesson> = emptyList(),
    val callings: List<String> = emptyList(),
    val priesthoodOrdinations: List<String> = emptyList(),
    val ministeringAssignments: List<String> = emptyList(),
    val templeOrdinances: List<String> = emptyList(),
    val templeExperiences: List<Toggle> = emptyList(),
    val selfReliance: List<Toggle> = emptyList(),
    val tags: List<String> = emptyList(),
) {
    /** Recorded "missed" count, tolerant of number-or-string jsonb; null when absent/unparseable. */
    val sacramentMissedCount: Int?
        get() = (sacramentMissed as? JsonPrimitive)?.contentOrNull?.toIntOrNull()
}

@Serializable
data class FriendRef(
    val name: String? = null,
    val unit: String? = null,
    val inStake: Boolean = false,
)

@Serializable
data class SacramentEntry(
    val label: String? = null,
    val attended: Boolean = false,
    val date: String? = null,
)

@Serializable
data class Lesson(
    val name: String? = null,
    val principles: List<Principle> = emptyList(),
)

@Serializable
data class Principle(
    val name: String? = null,
    val memberPresent: Boolean = false,
    // taughtLevel may arrive as a number OR a string in jsonb — keep it as a raw JsonElement so a
    // numeric value never breaks decoding. `taught` normalizes it (mirrors person_detail `_taught`).
    val taughtLevel: JsonElement? = null,
) {
    /** True when the principle was taught (non-null, non-zero). */
    val taught: Boolean
        get() {
            val s = (taughtLevel as? JsonPrimitive)?.contentOrNull ?: taughtLevel?.toString()
            return !s.isNullOrEmpty() && s != "0" && s != "0.0" && s != "null"
        }
}

/** A labeled on/off item ({name, done}) — temple experiences, self-reliance classes. */
@Serializable
data class Toggle(
    val name: String? = null,
    val done: Boolean = false,
)
