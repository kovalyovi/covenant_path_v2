package org.membercovenantpath.viewer.data

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject

/** Mirrors admin_client.dart's AdminException. */
class AdminException(message: String) : Exception(message)

/**
 * Calls the broker's admin/ops endpoints. Every request carries the signed-in user's Supabase access
 * token; the broker verifies it belongs to an app_admin (service-role check, RLS-independent).
 * Ported 1:1 from admin_client.dart.
 */
class AdminClient(private val accessToken: String) {

    val available: Boolean get() = AppConfig.brokerAvailable
    private val base: String get() = AppConfig.brokerUrl

    private fun ensure() {
        if (!available) throw AdminException("Ops console needs BROKER_URL configured.")
    }

    private suspend fun get(path: String): JsonObject {
        ensure()
        val resp = Net.getJson("$base$path", accessToken)
        return decode(resp.status.value, Net.bodyObject(resp))
    }

    private suspend fun post(path: String, body: JsonObject = JsonObject(emptyMap())): JsonObject {
        ensure()
        val resp = Net.postJson("$base$path", body, accessToken)
        return decode(resp.status.value, Net.bodyObject(resp))
    }

    private fun decode(status: Int, data: JsonObject): JsonObject {
        if (status == 403) throw AdminException("Not authorized (admins only).")
        if (status >= 400) throw AdminException(data.str("detail") ?: "Request failed ($status).")
        return data
    }

    suspend fun summary() = get("/admin/summary")
    suspend fun actions() = get("/admin/actions")
    suspend fun diagnostics() = get("/admin/diagnostics")
    suspend fun enrolledStakes() = get("/admin/enrolled-stakes")
    suspend fun revokeStake(stakeId: String) = post("/admin/stakes/$stakeId/revoke")
    /** Wipe a stake's member data (keeps the stake + roles + credential; repopulates next sync). */
    suspend fun wipeStakeData(stakeId: String) = post("/admin/stakes/$stakeId/wipe-data")
    /** Remove a stake completely (credential + members + roles + the stake row). Irreversible. */
    suspend fun removeStake(stakeId: String) = post("/admin/stakes/$stakeId/remove")
    suspend fun run(workflow: String, inputs: JsonObject? = null) =
        post("/admin/actions/run", buildJsonObject {
            put("workflow", JsonPrimitive(workflow))
            if (inputs != null) put("inputs", inputs)
        })
    suspend fun rerun(runId: Long) = post("/admin/actions/$runId/rerun")
    suspend fun invite(email: String) =
        post("/admin/invite", buildJsonObject { put("email", JsonPrimitive(email)) })
    suspend fun feedback(title: String, body: String) =
        post("/feedback", buildJsonObject {
            put("title", JsonPrimitive(title)); put("body", JsonPrimitive(body))
        })
}
