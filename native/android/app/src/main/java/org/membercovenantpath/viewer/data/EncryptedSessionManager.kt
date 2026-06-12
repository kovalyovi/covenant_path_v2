package org.membercovenantpath.viewer.data

import android.content.Context
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import io.github.jan.supabase.auth.SessionManager
import io.github.jan.supabase.auth.user.UserSession
import kotlinx.serialization.json.Json

/**
 * CLIENT-01: persist the Supabase session (access + long-lived REFRESH token) in Keystore-backed
 * [EncryptedSharedPreferences] instead of supabase-kt's default PLAINTEXT SharedPreferences, so a
 * lost/rooted device — or `adb backup` — can't lift the refresh token and mint fresh JWTs for the
 * leader's whole RLS scope. iOS already stores the session in the Keychain. `allowBackup=false`
 * (manifest) additionally keeps these prefs out of cloud/`adb` backups.
 *
 * AVD-VERIFY (per native/PARITY.md): confirm the supabase-kt 3.1.1 [SessionManager] method shape and
 * the [UserSession] import on a real device build — these shifted across 2.x/3.x. Construction is
 * wrapped in runCatching at the call site (SupabaseClientProvider) so an init failure degrades to
 * the default manager rather than crashing app startup.
 */
class EncryptedSessionManager(context: Context) : SessionManager {

    private val json = Json { ignoreUnknownKeys = true; isLenient = true }

    private val prefs = EncryptedSharedPreferences.create(
        context,
        "cp_auth",
        MasterKey.Builder(context).setKeyScheme(MasterKey.KeyScheme.AES256_GCM).build(),
        EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
        EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
    )

    override suspend fun saveSession(session: UserSession) {
        prefs.edit().putString(KEY, json.encodeToString(UserSession.serializer(), session)).apply()
    }

    override suspend fun loadSession(): UserSession? =
        prefs.getString(KEY, null)?.let {
            runCatching { json.decodeFromString(UserSession.serializer(), it) }.getOrNull()
        }

    override suspend fun deleteSession() {
        prefs.edit().remove(KEY).apply()
    }

    private companion object {
        const val KEY = "session"
    }
}
