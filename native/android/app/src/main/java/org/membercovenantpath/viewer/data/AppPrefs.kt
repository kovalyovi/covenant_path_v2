package org.membercovenantpath.viewer.data

import android.content.Context
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map

/** Theme preference (mirrors the Flutter ThemeController: system → light → dark cycle). */
enum class ThemeChoice { System, Light, Dark;
    val label: String get() = name
}

private val Context.dataStore by preferencesDataStore(name = "covenant_path_prefs")

/**
 * Persisted UI/account prefs via DataStore (the native analog of shared_preferences):
 *  • theme mode (theme/app_theme.dart ThemeController),
 *  • biometric app-lock toggle (biometric_gate.dart),
 *  • current stake id (dashboard_page.dart 'current_stake_id'),
 *  • one-time passkey-upsell flag (dashboard_page.dart 'passkey_suggested').
 */
class AppPrefs(private val context: Context) {

    private val themeKey = stringPreferencesKey("theme_mode")
    private val lockKey = booleanPreferencesKey("biometric_lock_enabled")
    private val stakeKey = stringPreferencesKey("current_stake_id")
    private val passkeySuggestedKey = booleanPreferencesKey("passkey_suggested")

    val theme: Flow<ThemeChoice> = context.dataStore.data.map { p ->
        when (p[themeKey]) {
            "light" -> ThemeChoice.Light
            "dark" -> ThemeChoice.Dark
            else -> ThemeChoice.System
        }
    }

    suspend fun setTheme(choice: ThemeChoice) {
        context.dataStore.edit { it[themeKey] = choice.name.lowercase() }
    }

    val appLock: Flow<Boolean> = context.dataStore.data.map { it[lockKey] ?: false }
    suspend fun setAppLock(on: Boolean) {
        context.dataStore.edit { it[lockKey] = on }
    }
    suspend fun appLockNow(): Boolean = appLock.first()

    val currentStakeId: Flow<String?> = context.dataStore.data.map { it[stakeKey] }
    suspend fun currentStakeIdNow(): String? = currentStakeId.first()
    suspend fun setCurrentStakeId(id: String) {
        context.dataStore.edit { it[stakeKey] = id }
    }

    suspend fun passkeySuggested(): Boolean = context.dataStore.data.map { it[passkeySuggestedKey] ?: false }.first()
    suspend fun markPasskeySuggested() {
        context.dataStore.edit { it[passkeySuggestedKey] = true }
    }
}
