package org.membercovenantpath.viewer.data

import io.ktor.client.HttpClient
import io.ktor.client.engine.okhttp.OkHttp
import io.ktor.client.request.get
import io.ktor.client.request.header
import io.ktor.client.request.post
import io.ktor.client.request.setBody
import io.ktor.client.statement.HttpResponse
import io.ktor.client.statement.bodyAsText
import io.ktor.http.ContentType
import io.ktor.http.HttpStatusCode
import io.ktor.http.contentType
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.jsonObject

/**
 * One shared Ktor [HttpClient] (OkHttp engine) for our broker/admin/passkey calls. We talk JSON
 * to the broker manually (encode the body, decode the reply) — the exact same shape the Flutter
 * `http`-based clients use — so there's no content-negotiation plugin to configure (one less thing
 * to break the CI build). supabase-kt keeps its own internal client; this is only for the broker.
 */
object Net {
    val json = Json {
        ignoreUnknownKeys = true
        isLenient = true
        encodeDefaults = true
        explicitNulls = false
    }

    // Explicit timeouts: OkHttp's 10s read default aborted any broker call slower than 10s — a
    // FIRST-ENROLL Church login runs the broker's access evaluation server-side (30-60s legitimately),
    // so enrollment could never complete from Android. 120s read mirrors the web client's 95s window
    // (plus margin for Render cold start).
    val client: HttpClient by lazy {
        HttpClient(OkHttp) {
            engine {
                config {
                    connectTimeout(20, java.util.concurrent.TimeUnit.SECONDS)
                    readTimeout(120, java.util.concurrent.TimeUnit.SECONDS)
                    writeTimeout(30, java.util.concurrent.TimeUnit.SECONDS)
                }
            }
        }
    }

    suspend fun postJson(url: String, body: JsonElement, bearer: String? = null): HttpResponse =
        client.post(url) {
            contentType(ContentType.Application.Json)
            if (bearer != null) header("Authorization", "Bearer $bearer")
            setBody(json.encodeToString(JsonElement.serializer(), body))
        }

    suspend fun getJson(url: String, bearer: String? = null): HttpResponse =
        client.get(url) {
            if (bearer != null) header("Authorization", "Bearer $bearer")
        }

    /** Decode a response body to a JsonObject (empty object when blank/unparseable). */
    suspend fun bodyObject(resp: HttpResponse): JsonObject =
        runCatching {
            val text = resp.bodyAsText()
            if (text.isBlank()) JsonObject(emptyMap())
            else json.parseToJsonElement(text).let { if (it is JsonObject) it else JsonObject(emptyMap()) }
        }.getOrDefault(JsonObject(emptyMap()))

    fun isError(resp: HttpResponse): Boolean = resp.status.value >= 400
}

// ---- small JsonObject accessors (mirror the Dart `j['x'] as T?` ergonomics) ----

fun JsonObject.str(key: String): String? =
    (this[key] as? kotlinx.serialization.json.JsonPrimitive)
        ?.takeIf { it !is JsonNull }
        ?.content
        ?.takeIf { it != "null" }

fun JsonObject.bool(key: String): Boolean =
    (this[key] as? kotlinx.serialization.json.JsonPrimitive)?.content?.equals("true", true) ?: false

/** Nullable bool: null when the key is absent/null/non-boolean (caller distinguishes "unknown"
 *  from an explicit false — used by N2's `authorized` so only a real `false` blocks login). */
fun JsonObject.boolOrNull(key: String): Boolean? =
    (this[key] as? kotlinx.serialization.json.JsonPrimitive)
        ?.takeIf { it !is JsonNull }
        ?.content?.let { when (it) { "true" -> true; "false" -> false; else -> null } }

fun JsonObject.int(key: String, default: Int = 0): Int =
    (this[key] as? kotlinx.serialization.json.JsonPrimitive)?.content?.toDoubleOrNull()?.toInt() ?: default

fun JsonObject.obj(key: String): JsonObject? = (this[key] as? JsonObject)

fun JsonObject.arr(key: String): kotlinx.serialization.json.JsonArray? =
    (this[key] as? kotlinx.serialization.json.JsonArray)
