package org.membercovenantpath.viewer.data

import io.github.jan.supabase.SupabaseClient
import io.github.jan.supabase.auth.Auth
import io.github.jan.supabase.createSupabaseClient
import io.github.jan.supabase.postgrest.Postgrest
import kotlinx.serialization.json.Json

/**
 * Single Supabase client for the app. URL + anon key come from [AppConfig]/BuildConfig (fed by gradle
 * properties / env — never hardcoded). The anon key is safe on clients; RLS does all gating.
 *
 * supabase-kt 3.x: `auth-kt` (formerly gotrue-kt) + `postgrest-kt`, installed via the DSL.
 */
object SupabaseClientProvider {

    val isConfigured: Boolean get() = AppConfig.supabaseConfigured

    // Lenient JSON so a partial/extra `details` subtree never breaks decoding of a Member row.
    private val lenientJson = Json {
        ignoreUnknownKeys = true
        coerceInputValues = true
        isLenient = true
    }

    val client: SupabaseClient by lazy {
        createSupabaseClient(
            supabaseUrl = AppConfig.supabaseUrl,
            supabaseKey = AppConfig.supabaseAnonKey,
        ) {
            install(Auth)
            install(Postgrest)
            defaultSerializer = io.github.jan.supabase.serializer.KotlinXSerializer(lenientJson)
        }
    }
}
