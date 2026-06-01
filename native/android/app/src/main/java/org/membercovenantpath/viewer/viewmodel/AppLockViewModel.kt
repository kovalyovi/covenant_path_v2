package org.membercovenantpath.viewer.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import org.membercovenantpath.viewer.data.AppPrefs

/**
 * Persisted biometric app-lock preference (the gate prompt itself runs in the UI via BiometricPrompt,
 * which needs an Activity). Mirrors biometric_gate.dart's enabled()/setEnabled() persistence.
 */
class AppLockViewModel(private val prefs: AppPrefs) : ViewModel() {

    val enabled: StateFlow<Boolean> =
        prefs.appLock.stateIn(viewModelScope, SharingStarted.Eagerly, false)

    fun set(on: Boolean) {
        viewModelScope.launch { prefs.setAppLock(on) }
    }
}
