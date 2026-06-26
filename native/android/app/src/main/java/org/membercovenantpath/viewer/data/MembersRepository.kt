package org.membercovenantpath.viewer.data

import io.github.jan.supabase.SupabaseClient
import io.github.jan.supabase.postgrest.postgrest
import io.github.jan.supabase.postgrest.query.Columns
import io.github.jan.supabase.postgrest.query.Order
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.membercovenantpath.viewer.model.Member
import org.membercovenantpath.viewer.model.Missionary
import org.membercovenantpath.viewer.model.Stake

/** The client-safe `maintenance_status` view (owner-only maintenance mode, migration 0056). Exposes
 *  ONLY the public flag + message — never the owner email. Mirrors the web `maintenance_status` select. */
@Serializable
data class MaintenanceStatus(
    @SerialName("maintenance_mode") val maintenanceMode: Boolean? = null,
    @SerialName("maintenance_message") val maintenanceMessage: String? = null,
)

/**
 * Read-only Supabase access for `members` + `stakes`. The app does NO filtering of its own — RLS
 * returns only allowed rows. We scope the dashboard to ONE stake (`.eq("stake_id", id)`) exactly
 * like dashboard_page.dart `_load`, so a multi-stake power user never sees a merged union.
 */
class MembersRepository(
    private val client: SupabaseClient = SupabaseClientProvider.client,
) {
    companion object {
        // Mirror dashboard_page.dart `_columns` verbatim (order matters only for readability).
        val MEMBER_COLUMNS = Columns.raw(
            "person_uuid, stake_id, unit_id, name, unit_name, baptism_date, birth_date, " +
                "membership_duration, sex, friends, friends_count, aaronic_priesthood, melchizedek_priesthood, " +
                "calling, ministering_brothers_sisters, ministering_assignment, temple_recommend, " +
                "patriarchal_blessing, living_ordinance, family_name_prepared, first_temple_visit, " +
                "details, photo_url, kind, baptism_goal_date",
        )
    }

    /** All stakes the signed-in user may see (RLS-scoped), freshest first. */
    suspend fun loadStakes(): List<Stake> {
        val stakes = client.postgrest.from("stakes")
            .select(Columns.raw("id, name, unit_number, last_synced_at, sync_state, sync_started_at, missionaries, sheets_enabled"))
            .decodeList<Stake>()
        return stakes.sortedByDescending { it.lastSyncedAt ?: "" }
    }

    /** Whether the signed-in user is an app_admin (server RPC `is_admin`). False on any error. */
    suspend fun isAdmin(): Boolean =
        runCatching { client.postgrest.rpc("is_admin").decodeAs<Boolean>() }.getOrDefault(false)

    /** Owner-only maintenance mode (migration 0056): is the signed-in user the single OWNER? */
    suspend fun isOwner(): Boolean =
        runCatching { client.postgrest.rpc("is_owner").decodeAs<Boolean>() }.getOrDefault(false)

    /** The global maintenance switch + optional message (client-safe view; never the owner email). */
    suspend fun maintenanceStatus(): MaintenanceStatus =
        runCatching {
            client.postgrest.from("maintenance_status")
                .select(Columns.raw("maintenance_mode, maintenance_message"))
                .decodeList<MaintenanceStatus>().firstOrNull()
        }.getOrNull() ?: MaintenanceStatus()

    /** #5b: a stake leader toggles Google-Sheet generation for their stake (RPC enforces the role). */
    suspend fun setStakeSheetsEnabled(stakeId: String, enabled: Boolean) {
        client.postgrest.rpc("set_stake_sheets_enabled", kotlinx.serialization.json.buildJsonObject {
            put("p_stake_id", kotlinx.serialization.json.JsonPrimitive(stakeId))
            put("p_enabled", kotlinx.serialization.json.JsonPrimitive(enabled))
        })
    }

    /** Members for ONE stake, ordered by unit_name then name (matches the Flutter select). */
    suspend fun loadMembers(stakeId: String): List<Member> =
        client.postgrest.from("members")
            .select(MEMBER_COLUMNS) {
                filter { eq("stake_id", stakeId) }
                order("unit_name", Order.ASCENDING)
                order("name", Order.ASCENDING)
            }
            .decodeList<Member>()

    /** Decode a stake's `missionaries` jsonb (unit name → [{name,phone,email}]). */
    fun missionariesByUnit(stake: Stake): Map<String, List<Missionary>> {
        val obj = stake.missionaries as? JsonObject ?: return emptyMap()
        val out = LinkedHashMap<String, List<Missionary>>()
        for ((unit, value) in obj) {
            val arr = value as? JsonArray ?: continue
            out[unit] = arr.mapNotNull { el ->
                val o = el.jsonObject
                Missionary(
                    name = o["name"]?.jsonPrimitive?.contentOrNull,
                    phone = o["phone"]?.jsonPrimitive?.contentOrNull,
                    email = o["email"]?.jsonPrimitive?.contentOrNull,
                    photoUrl = o["photo_url"]?.jsonPrimitive?.contentOrNull,
                )
            }
        }
        return out
    }
}
