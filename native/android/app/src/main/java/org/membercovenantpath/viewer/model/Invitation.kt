package org.membercovenantpath.viewer.model

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/** A row of `invitations` (power-user grants). Multiple scope rows can share an email. */
@Serializable
data class Invitation(
    @SerialName("invited_email") val invitedEmail: String? = null,
    @SerialName("role") val role: String? = null,
    @SerialName("unit_id") val unitId: String? = null,
    @SerialName("status") val status: String? = null,
    @SerialName("invited_by_email") val invitedByEmail: String? = null,
    @SerialName("created_at") val createdAt: String? = null,
)

/** A `units` row (id + name) for the invite scope dropdown + admin views. */
@Serializable
data class Unit(
    @SerialName("id") val id: String,
    @SerialName("name") val name: String? = null,
)

/** An `app_admins` row (admin console). */
@Serializable
data class AppAdmin(
    @SerialName("email") val email: String? = null,
    @SerialName("invited_by_email") val invitedByEmail: String? = null,
)
