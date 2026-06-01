package org.membercovenantpath.viewer.model

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement

/**
 * `stakes` row. `missionaries` is a free-form jsonb map of unit-name → [{name, phone, email}];
 * kept as a raw [JsonElement] and decoded lazily by the repository into [Missionary] lists.
 */
@Serializable
data class Stake(
    @SerialName("id") val id: String,
    @SerialName("name") val name: String? = null,
    @SerialName("unit_number") val unitNumber: String? = null,
    @SerialName("last_synced_at") val lastSyncedAt: String? = null,
    @SerialName("missionaries") val missionaries: JsonElement? = null,
)

@Serializable
data class Missionary(
    @SerialName("name") val name: String? = null,
    @SerialName("phone") val phone: String? = null,
    @SerialName("email") val email: String? = null,
)
