package org.membercovenantpath.viewer.data

import io.ktor.client.statement.HttpResponse
import kotlinx.coroutines.delay
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject

/** Mirrors broker_client.dart's exceptions/result types so the UI logic ports 1:1. */
class BrokerException(message: String) : Exception(message)

/** One MFA factor offered by Okta (e.g. "Text message to •••1234"). */
data class BrokerFactor(val id: String, val label: String, val method: String) {
    companion object {
        fun from(j: JsonObject) = BrokerFactor(
            id = j.str("id") ?: "",
            label = j.str("label") ?: j.str("method") ?: "Code",
            method = j.str("method") ?: "",
        )
    }
}

/** Result of a broker step: a verifiable Supabase session, or an MFA challenge to continue. */
data class BrokerResult(
    val email: String? = null,
    val otp: String? = null,
    val loginId: String? = null,
    val factors: List<BrokerFactor> = emptyList(),
    val name: String? = null,
    // N2: covenant-path access from the broker enroll step. null = unknown (don't block);
    // false = no access -> block at login.
    val authorized: Boolean? = null,
) {
    val mfaRequired: Boolean get() = loginId != null && otp == null
}

/** Credential state from /auth/enrollment-status. */
data class CredentialInfo(
    val state: String = "none",
    val complete: Boolean = false,
    val principalName: String? = null,
    val isProvider: Boolean = false,
    val enrolledAt: String? = null,
) {
    val isActive get() = state == "active"
    val isRevoked get() = state == "revoked"
    val isNone get() = state == "none"

    companion object {
        fun from(j: JsonObject?) = CredentialInfo(
            state = j?.str("state") ?: "none",
            complete = j?.bool("complete") ?: false,
            principalName = j?.str("principal_name"),
            isProvider = j?.bool("is_provider") ?: false,
            enrolledAt = j?.str("enrolled_at"),
        )
    }
}

/** Response from /auth/enrollment-status. */
data class EnrollmentStatus(
    val stakeName: String? = null,
    val stakeId: String? = null,
    val lastSyncedAt: String? = null,
    val memberCount: Int = 0,
    val hasData: Boolean = false,
    val noRole: Boolean = false,
    val credential: CredentialInfo = CredentialInfo(),
) {
    companion object {
        fun from(j: JsonObject) = EnrollmentStatus(
            stakeName = j.str("stake_name"),
            stakeId = j.str("stake_id"),
            lastSyncedAt = j.str("last_synced_at"),
            memberCount = j.int("member_count"),
            hasData = j.bool("has_data"),
            noRole = j.str("status") == "no_role",
            credential = CredentialInfo.from(j.obj("credential")),
        )
    }
}

/**
 * Thin client for the Church-login auth broker (backend/auth_broker). Ported from broker_client.dart
 * — same endpoints, same cold-start retry, same MFA flow. Authed calls carry the signed-in user's
 * Supabase access token (from [auth]). Empty BROKER_URL => `available` is false.
 */
class BrokerClient(private val auth: AuthRepository = AuthRepository()) {

    val available: Boolean get() = AppConfig.brokerAvailable
    private val base: String get() = AppConfig.brokerUrl

    /** Called when a network attempt fails and we're about to retry — UI shows a "waking up…" note. */
    var onStatus: ((String) -> Unit)? = null

    /** N5: wake the free-tier broker early (cheap /health ping) so it's warm by the time the user
     *  submits credentials, hiding the ~60s cold start. Best-effort; errors swallowed. */
    suspend fun warmUp() {
        if (!available) return
        runCatching { Net.getJson("$base/health") }
    }

    // Free hosting (Render) sleeps when idle; the first request after a sleep fails. Retry across
    // ~60s so a cold start resolves itself instead of erroring out. Delays sum to ~63s (matches Dart).
    private val retryDelaysMs = longArrayOf(3000, 6000, 9000, 12000, 15000, 18000)

    private fun requireToken(): String =
        auth.accessToken?.takeIf { it.isNotEmpty() } ?: throw BrokerException("Not signed in.")

    /** POST with cold-start retry; returns the decoded JSON (throws BrokerException on error). */
    private suspend fun postJsonRetry(path: String, body: JsonObject): JsonObject {
        if (!available) throw BrokerException("Church login is not configured (BROKER_URL).")
        var resp: HttpResponse? = null
        var lastErr: Throwable? = null
        for (attempt in 0..retryDelaysMs.size) {
            try {
                resp = Net.postJson("$base$path", body)
                break // got an HTTP response (success or error) — stop retrying
            } catch (e: Throwable) {
                lastErr = e
                if (attempt < retryDelaysMs.size) {
                    onStatus?.invoke("Waking up the sign-in service… this can take up to a minute on first use.")
                    delay(retryDelaysMs[attempt])
                }
            }
        }
        if (resp == null) {
            throw BrokerException(
                "Could not reach the sign-in service after several tries. It may be starting up — " +
                    "please try again in a minute. ($lastErr)",
            )
        }
        val data = Net.bodyObject(resp)
        if (Net.isError(resp)) {
            throw BrokerException(data.str("detail") ?: "Sign-in failed (${resp.status.value}).")
        }
        return data
    }

    private suspend fun post(path: String, body: JsonObject): BrokerResult {
        val data = postJsonRetry(path, body)
        if (data.str("status") == "mfa_required") {
            return BrokerResult(
                loginId = data.str("login_id"),
                factors = data.arr("factors")?.mapNotNull { (it as? JsonObject)?.let(BrokerFactor::from) } ?: emptyList(),
            )
        }
        val session = data.obj("session") ?: JsonObject(emptyMap())
        return BrokerResult(
            email = session.str("email"),
            otp = session.str("otp"),
            name = data.str("identity_name"),
            // N2: only an explicit false blocks; absent/errored enroll → null (don't block).
            authorized = data.obj("enroll")?.boolOrNull("authorized"),
        )
    }

    suspend fun password(username: String, password: String, enroll: Boolean = false): BrokerResult =
        post("/auth/password", buildJsonObject {
            put("username", JsonPrimitive(username)); put("password", JsonPrimitive(password)); put("enroll", JsonPrimitive(enroll))
        })

    suspend fun selectFactor(loginId: String, factorId: String): BrokerResult =
        post("/auth/mfa/select", buildJsonObject {
            put("login_id", JsonPrimitive(loginId)); put("factor_id", JsonPrimitive(factorId))
        })

    suspend fun verifyMfa(loginId: String, code: String, enroll: Boolean = false): BrokerResult =
        post("/auth/mfa/verify", buildJsonObject {
            put("login_id", JsonPrimitive(loginId)); put("code", JsonPrimitive(code)); put("enroll", JsonPrimitive(enroll))
        })

    /** Email-OTP relay (networks that can't reach Supabase directly): broker emails the code. */
    suspend fun emailStart(email: String) {
        postJsonRetry("/auth/email/start", buildJsonObject { put("email", JsonPrimitive(email)) })
    }

    /** Verify the emailed code via the broker → {access_token, refresh_token} for adoptRefreshToken. */
    suspend fun emailVerify(email: String, code: String): JsonObject =
        postJsonRetry("/auth/email/verify", buildJsonObject {
            put("email", JsonPrimitive(email)); put("code", JsonPrimitive(code))
        })

    suspend fun enrollmentStatus(): EnrollmentStatus {
        val resp = Net.getJson("$base/auth/enrollment-status", requireToken())
        val data = Net.bodyObject(resp)
        if (Net.isError(resp)) throw BrokerException(data.str("detail") ?: "Enrollment status failed.")
        return EnrollmentStatus.from(data)
    }

    suspend fun revoke(stakeId: String) {
        authed("POST", "/auth/revoke", buildJsonObject { put("stake_id", JsonPrimitive(stakeId)) })
    }

    /** Provider triggers a sync for their own stake. Returns {coverage_complete, last_synced_at}. */
    suspend fun syncNow(): JsonObject = authed("POST", "/auth/sync-now")

    suspend fun getSchedule(): JsonObject = authed("GET", "/auth/schedule")
    suspend fun setSchedule(hourEt: Int, paused: Boolean): JsonObject =
        authed("POST", "/auth/schedule", buildJsonObject {
            put("hour_et", JsonPrimitive(hourEt)); put("paused", JsonPrimitive(paused))
        })

    suspend fun googleDriveStatus(): JsonObject = authed("GET", "/auth/google/status")
    suspend fun googleDriveStart(): JsonObject = authed("POST", "/auth/google/start")
    suspend fun googleDriveDisconnect(): JsonObject = authed("POST", "/auth/google/disconnect")

    suspend fun contact(subject: String, message: String) {
        authed("POST", "/contact", buildJsonObject {
            put("subject", JsonPrimitive(subject)); put("message", JsonPrimitive(message))
        })
    }

    suspend fun report(): JsonObject = authed("GET", "/report")
    suspend fun emailReport(toEmail: String? = null): JsonObject =
        authed("POST", "/report/email", buildJsonObject {
            if (!toEmail.isNullOrEmpty()) put("to_email", JsonPrimitive(toEmail))
        })

    /** Shared authed request carrying the signed-in user's Supabase token. */
    private suspend fun authed(method: String, path: String, body: JsonObject = JsonObject(emptyMap())): JsonObject {
        if (!available) throw BrokerException("Broker not configured.")
        val token = requireToken()
        val resp = if (method == "GET") Net.getJson("$base$path", token) else Net.postJson("$base$path", body, token)
        val data = Net.bodyObject(resp)
        if (Net.isError(resp)) throw BrokerException(data.str("detail") ?: "Request failed (${resp.status.value}).")
        return data
    }
}
