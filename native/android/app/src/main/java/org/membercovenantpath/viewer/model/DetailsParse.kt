package org.membercovenantpath.viewer.model

import org.membercovenantpath.viewer.data.SupabaseClientProvider

/**
 * Decode the loose `members.details` jsonb into the typed [Details] model. The subtree is often
 * partial — the lenient JSON (ignoreUnknownKeys + coerceInputValues + isLenient) tolerates missing
 * keys and a numeric-vs-string `taughtLevel`. Returns null when there's no usable subtree (the
 * detail page then falls back to the flat fields, exactly like the Flutter app).
 */
fun Member.parsedDetails(): Details? {
    val raw = details ?: return null
    return runCatching {
        SupabaseClientProvider.json.decodeFromJsonElement(Details.serializer(), raw)
    }.getOrNull()
}
