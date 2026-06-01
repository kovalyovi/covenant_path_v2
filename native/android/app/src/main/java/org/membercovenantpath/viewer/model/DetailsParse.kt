package org.membercovenantpath.viewer.model

import kotlinx.serialization.json.Json

/**
 * Decode the loose `members.details` jsonb into the typed [Details] model. The subtree is often
 * partial — the lenient JSON (ignoreUnknownKeys + coerceInputValues + isLenient) tolerates missing
 * keys and a numeric-vs-string `taughtLevel`. Returns null when there's no usable subtree (the
 * detail page then falls back to the flat fields, exactly like the Flutter app).
 *
 * Uses its own lenient [Json] (not the Supabase client's) so the pure logic/model layer — and the
 * KPI math that reads sacrament/lessons — stays unit-testable without an Android/Supabase context.
 */
private val detailsJson = Json {
    ignoreUnknownKeys = true
    coerceInputValues = true
    isLenient = true
}

fun Member.parsedDetails(): Details? {
    val raw = details ?: return null
    return runCatching { detailsJson.decodeFromJsonElement(Details.serializer(), raw) }.getOrNull()
}
