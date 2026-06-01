package org.membercovenantpath.viewer.model

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/** One row of `member_comments` (read shape: author + body + timestamp). RLS-scoped. */
@Serializable
data class Comment(
    @SerialName("author_email") val authorEmail: String? = null,
    @SerialName("author_name") val authorName: String? = null,
    @SerialName("body") val body: String? = null,
    @SerialName("created_at") val createdAt: String? = null,
) {
    val who: String get() = (authorName?.takeIf { it.isNotBlank() } ?: authorEmail ?: "").trim()
}

/** Insert shape for a new note (matches person_detail_page.dart `_post`). */
@Serializable
data class CommentInsert(
    @SerialName("stake_id") val stakeId: String?,
    @SerialName("unit_id") val unitId: String?,
    @SerialName("member_person_uuid") val memberPersonUuid: String,
    @SerialName("author_email") val authorEmail: String,
    @SerialName("body") val body: String,
)
