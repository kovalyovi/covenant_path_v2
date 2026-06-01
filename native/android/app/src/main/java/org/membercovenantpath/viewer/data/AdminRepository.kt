package org.membercovenantpath.viewer.data

import io.github.jan.supabase.SupabaseClient
import io.github.jan.supabase.postgrest.postgrest
import io.github.jan.supabase.postgrest.query.Columns
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import org.membercovenantpath.viewer.model.AppAdmin

/** Supabase-side bits of the admin console: the admins list + the escalation-safe revoke RPC. */
class AdminRepository(
    private val client: SupabaseClient = SupabaseClientProvider.client,
) {
    suspend fun loadAdmins(): List<AppAdmin> =
        client.postgrest.from("app_admins")
            .select(Columns.raw("email, invited_by_email"))
            .decodeList<AppAdmin>()

    suspend fun revokeAdmin(email: String) {
        client.postgrest.rpc("revoke_admin", buildJsonObject { put("p_email", JsonPrimitive(email)) })
    }
}
