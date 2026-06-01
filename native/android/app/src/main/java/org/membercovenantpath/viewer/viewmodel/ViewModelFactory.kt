package org.membercovenantpath.viewer.viewmodel

import android.content.Context
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import org.membercovenantpath.viewer.data.AppPrefs

/**
 * A tiny ViewModel factory for the few ViewModels that need a [Context]-backed [AppPrefs]
 * (theme/app-lock/stake persistence). Keeps construction explicit without pulling in a DI framework.
 */
class AppViewModelFactory(context: Context) : ViewModelProvider.Factory {
    private val appContext = context.applicationContext
    private val prefs = AppPrefs(appContext)

    @Suppress("UNCHECKED_CAST")
    override fun <T : ViewModel> create(modelClass: Class<T>): T = when {
        modelClass.isAssignableFrom(DashboardViewModel::class.java) -> DashboardViewModel(prefs = prefs) as T
        modelClass.isAssignableFrom(ThemeViewModel::class.java) -> ThemeViewModel(prefs) as T
        modelClass.isAssignableFrom(AppLockViewModel::class.java) -> AppLockViewModel(prefs) as T
        modelClass.isAssignableFrom(AuthViewModel::class.java) -> AuthViewModel() as T
        modelClass.isAssignableFrom(InviteViewModel::class.java) -> InviteViewModel() as T
        modelClass.isAssignableFrom(AdminViewModel::class.java) -> AdminViewModel() as T
        modelClass.isAssignableFrom(ActionsViewModel::class.java) -> ActionsViewModel() as T
        else -> throw IllegalArgumentException("Unknown ViewModel: ${modelClass.name}")
    }
}
