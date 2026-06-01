package org.membercovenantpath.viewer.data

import org.membercovenantpath.viewer.BuildConfig

/**
 * Build-time config (mirrors the Flutter `config.dart`). All values come from [BuildConfig], fed by
 * gradle properties / env, defaulting to "" — no secrets in source. The anon key is safe on clients
 * (RLS gates everything); [brokerUrl] empty => Church login / passkeys / reports / admin are hidden.
 */
object AppConfig {
    val supabaseUrl: String get() = BuildConfig.SUPABASE_URL
    val supabaseAnonKey: String get() = BuildConfig.SUPABASE_ANON_KEY
    val brokerUrl: String get() = BuildConfig.BROKER_URL.trimEnd('/')

    val supabaseConfigured: Boolean get() = supabaseUrl.isNotBlank() && supabaseAnonKey.isNotBlank()
    val brokerAvailable: Boolean get() = brokerUrl.isNotBlank()
}
