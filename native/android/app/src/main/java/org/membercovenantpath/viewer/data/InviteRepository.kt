package org.membercovenantpath.viewer.data

import io.github.jan.supabase.SupabaseClient
import io.github.jan.supabase.postgrest.postgrest
import io.github.jan.supabase.postgrest.query.Columns
import io.github.jan.supabase.postgrest.query.Order
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import org.membercovenantpath.viewer.model.Invitation
import org.membercovenantpath.viewer.model.Unit

/**
 * Power-user management (invite_page.dart): list current grants, list assignable units, and the
 * escalation-safe RPCs `invite_power_user` (clones the caller's scopes to an email) /
 * `revoke_power_user`. RLS + the RPCs enforce that you can only clone what you hold.
 */
class InviteRepository(
    private val client: SupabaseClient = SupabaseClientProvider.client,
) {
    suspend fun loadInvitations(): List<Invitation> =
        client.postgrest.from("invitations")
            .select(Columns.raw("invited_email, role, unit_id, status, invited_by_email, created_at")) {
                order("created_at", Order.DESCENDING)
            }
            .decodeList<Invitation>()

    /** Units the caller can scope an invite to (RLS may return none — the "everything" option works). */
    suspend fun loadUnits(): List<Unit> =
        runCatching {
            client.postgrest.from("units")
                .select(Columns.raw("id, name")) { order("name", Order.ASCENDING) }
                .decodeList<Unit>()
        }.getOrDefault(emptyList())

    /** Returns the number of scopes granted. `p_unit` null => everything the inviter can see. */
    suspend fun invite(email: String, unitId: String?): Int {
        val params = buildJsonObject {
            put("p_email", JsonPrimitive(email))
            if (unitId != null) put("p_unit", JsonPrimitive(unitId))
        }
        return client.postgrest.rpc("invite_power_user", params).decodeAs<Int>()
    }

    suspend fun revoke(email: String) {
        client.postgrest.rpc("revoke_power_user", buildJsonObject { put("p_email", JsonPrimitive(email)) })
    }
}
