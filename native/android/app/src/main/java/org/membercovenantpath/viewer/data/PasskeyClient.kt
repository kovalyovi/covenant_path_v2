package org.membercovenantpath.viewer.data

import android.content.Context
import androidx.credentials.CreatePublicKeyCredentialRequest
import androidx.credentials.CreatePublicKeyCredentialResponse
import androidx.credentials.CredentialManager
import androidx.credentials.GetCredentialRequest
import androidx.credentials.GetPublicKeyCredentialOption
import androidx.credentials.PublicKeyCredential
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject

/**
 * Passwordless passkey (WebAuthn) login + registration, against the broker's /webauthn  routes —
 * the native analog of passkey_client.dart. The broker returns standard WebAuthn options JSON,
 * which Android's Credential Manager consumes directly (GetPublicKeyCredentialOption /
 * CreatePublicKeyCredentialRequest), and returns the credential JSON the broker's /complete expects.
 *
 * Requires an Activity [Context] (Credential Manager shows system UI). Login is unauthenticated
 * (it IS the sign-in); registration carries the current Supabase session.
 */
class PasskeyClient(
    private val auth: AuthRepository = AuthRepository(),
) {
    val available: Boolean get() = AppConfig.brokerAvailable
    private val base: String get() = AppConfig.brokerUrl

    private suspend fun post(path: String, body: JsonObject, bearer: String? = null): JsonObject {
        val resp = Net.postJson("$base$path", body, bearer)
        val data = Net.bodyObject(resp)
        if (Net.isError(resp)) throw BrokerException(data.str("detail") ?: "Passkey request failed.")
        return data
    }

    /** Passwordless login → a verifiable Supabase session ({email, otp}) to verifyBrokerOtp. */
    suspend fun login(context: Context): BrokerResult {
        val begin = post("/webauthn/login/begin", JsonObject(emptyMap()))
        val optionsJson = Net.json.encodeToString(JsonObject.serializer(), begin.obj("options") ?: JsonObject(emptyMap()))

        val request = GetCredentialRequest(listOf(GetPublicKeyCredentialOption(requestJson = optionsJson)))
        val result = CredentialManager.create(context).getCredential(context, request)
        val cred = result.credential as? PublicKeyCredential
            ?: throw BrokerException("No passkey returned.")
        val credentialJson = Net.json.parseToJsonElement(cred.authenticationResponseJson)

        val done = post("/webauthn/login/complete", buildJsonObject {
            begin["handle"]?.let { put("handle", it) }
            put("credential", credentialJson)
        })
        val session = done.obj("session") ?: JsonObject(emptyMap())
        return BrokerResult(email = session.str("email"), otp = session.str("otp"))
    }

    /** Register a passkey for the signed-in user (requires a current Supabase session). */
    suspend fun register(context: Context) {
        val token = auth.accessToken?.takeIf { it.isNotEmpty() } ?: throw BrokerException("Not signed in.")
        val begin = post("/webauthn/register/begin", JsonObject(emptyMap()), bearer = token)
        val optionsJson = Net.json.encodeToString(JsonObject.serializer(), begin.obj("options") ?: JsonObject(emptyMap()))

        val request = CreatePublicKeyCredentialRequest(requestJson = optionsJson)
        val result = CredentialManager.create(context).createCredential(context, request)
        val response = result as? CreatePublicKeyCredentialResponse
            ?: throw BrokerException("Passkey creation failed.")
        val credentialJson = Net.json.parseToJsonElement(response.registrationResponseJson)

        post("/webauthn/register/complete", buildJsonObject {
            begin["handle"]?.let { put("handle", it) }
            put("credential", credentialJson)
        }, bearer = token)
    }
}
