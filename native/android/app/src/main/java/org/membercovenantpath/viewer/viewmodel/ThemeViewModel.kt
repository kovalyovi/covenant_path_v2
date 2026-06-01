package org.membercovenantpath.viewer.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import org.membercovenantpath.viewer.data.AppPrefs
import org.membercovenantpath.viewer.data.ThemeChoice

/**
 * App-wide light/dark/system preference (persisted via DataStore). The native analog of the Flutter
 * ThemeController — same system → light → dark cycle and the same persistence semantics.
 */
class ThemeViewModel(private val prefs: AppPrefs) : ViewModel() {

    // Initial value Light so the very first frame (login) isn't dark on a dark-mode device before
    // DataStore emits the persisted choice; an explicit saved System/Dark then takes over.
    val theme: StateFlow<ThemeChoice> =
        prefs.theme.stateIn(viewModelScope, SharingStarted.Eagerly, ThemeChoice.Light)

    fun set(choice: ThemeChoice) {
        viewModelScope.launch { prefs.setTheme(choice) }
    }

    fun cycle() {
        viewModelScope.launch {
            prefs.setTheme(
                when (theme.value) {
                    ThemeChoice.System -> ThemeChoice.Light
                    ThemeChoice.Light -> ThemeChoice.Dark
                    ThemeChoice.Dark -> ThemeChoice.System
                },
            )
        }
    }
}
