package org.membercovenantpath.viewer.ui

import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import org.membercovenantpath.viewer.data.AppConfig
import org.membercovenantpath.viewer.ui.screens.AdminScreen
import org.membercovenantpath.viewer.ui.screens.BiometricGate
import org.membercovenantpath.viewer.ui.screens.ConfigErrorScreen
import org.membercovenantpath.viewer.ui.screens.DashboardScaffold
import org.membercovenantpath.viewer.ui.screens.InviteScreen
import org.membercovenantpath.viewer.ui.screens.LoginScreen
import org.membercovenantpath.viewer.ui.screens.PersonDetailScreen
import org.membercovenantpath.viewer.ui.screens.SettingsScreen
import org.membercovenantpath.viewer.ui.theme.CovenantPathTheme
import org.membercovenantpath.viewer.viewmodel.ActionsViewModel
import org.membercovenantpath.viewer.viewmodel.AppLockViewModel
import org.membercovenantpath.viewer.viewmodel.AppViewModelFactory
import org.membercovenantpath.viewer.viewmodel.AuthGate
import org.membercovenantpath.viewer.viewmodel.AuthViewModel
import org.membercovenantpath.viewer.viewmodel.DashboardViewModel
import org.membercovenantpath.viewer.viewmodel.ThemeViewModel

private object Routes {
    const val DASHBOARD = "dashboard"
    const val DETAIL = "detail/{uuid}"
    const val SETTINGS = "settings"
    const val INVITE = "invite"
    const val ADMIN = "admin"
    fun detail(uuid: String) = "detail/$uuid"
}

/**
 * App root: persisted theme + auth gate + biometric app-lock + nav graph. Routes between Login and
 * the Dashboard off the Supabase session (AuthGate); a blank Supabase config shows a config screen
 * (mirrors the Flutter `_ConfigError`). Theme follows the saved light/dark/system choice.
 */
@Composable
fun App() {
    val context = LocalContext.current
    val factory = remember { AppViewModelFactory(context) }
    val themeVm: ThemeViewModel = viewModel(factory = factory)
    val theme by themeVm.theme.collectAsStateWithLifecycle()

    CovenantPathTheme(choice = theme) {
        // Paint the themed background behind every gate state — MaterialTheme alone doesn't fill one,
        // so the Scaffold-less screens (Login / Loading / ConfigError) would otherwise show the dark
        // window background even under the light scheme. (This was the "login screen is dark" bug.)
        Surface(modifier = Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
            if (!AppConfig.supabaseConfigured) {
                ConfigErrorScreen()
            } else {
                val authVm: AuthViewModel = viewModel(factory = factory)
                val gate by authVm.gate.collectAsStateWithLifecycle()

                when (gate) {
                    AuthGate.Loading -> org.membercovenantpath.viewer.ui.screens.CenteredLoading()
                    AuthGate.SignedOut -> LoginScreen(authVm)
                    AuthGate.SignedIn -> {
                        val lockVm: AppLockViewModel = viewModel(factory = factory)
                        val lockOn by lockVm.enabled.collectAsStateWithLifecycle()
                        BiometricGate(lockEnabled = lockOn) {
                            SignedInNav(themeVm = themeVm, lockVm = lockVm, factory = factory, onSignOut = authVm::signOut)
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun SignedInNav(
    themeVm: ThemeViewModel,
    lockVm: AppLockViewModel,
    factory: AppViewModelFactory,
    onSignOut: () -> Unit,
) {
    val dashVm: DashboardViewModel = viewModel(factory = factory)
    val actionsVm: ActionsViewModel = viewModel(factory = factory)
    val state by dashVm.state.collectAsStateWithLifecycle()
    val nav = rememberNavController()

    NavHost(navController = nav, startDestination = Routes.DASHBOARD) {
        composable(Routes.DASHBOARD) {
            DashboardScaffold(
                state = state,
                dashVm = dashVm,
                actionsVm = actionsVm,
                onOpenMember = { m -> m.personUuid?.let { nav.navigate(Routes.detail(it)) } },
                onSignOut = onSignOut,
                onOpenSettings = { nav.navigate(Routes.SETTINGS) },
                onOpenInvite = { nav.navigate(Routes.INVITE) },
                onOpenAdmin = { nav.navigate(Routes.ADMIN) },
            )
        }
        composable(
            route = Routes.DETAIL,
            arguments = listOf(navArgument("uuid") { type = NavType.StringType }),
        ) { entry ->
            val uuid = entry.arguments?.getString("uuid")
            val member = state.members.firstOrNull { it.personUuid == uuid }
            if (member != null) {
                PersonDetailScreen(
                    member = member,
                    onBack = { nav.popBackStack() },
                    onNotesChanged = dashVm::reloadNotes,
                )
            } else {
                nav.popBackStack()
            }
        }
        composable(Routes.SETTINGS) {
            SettingsScreen(
                themeVm = themeVm,
                lockVm = lockVm,
                actionsVm = actionsVm,
                email = AuthViewModelEmail(),
                onBack = { nav.popBackStack() },
                onSignOut = { onSignOut() },
                stakeId = state.currentStakeId,
                sheetsEnabled = state.currentStake?.sheetsEnabled ?: false,
                onToggleSheets = { dashVm.setSheetsEnabled(state.currentStakeId, it) },
            )
        }
        composable(Routes.INVITE) { InviteScreen(onBack = { nav.popBackStack() }) }
        composable(Routes.ADMIN) { AdminScreen(onBack = { nav.popBackStack() }) }
    }
}

/** Convenience: the signed-in email straight from the auth repository (no extra VM plumbing). */
@Composable
private fun AuthViewModelEmail(): String =
    org.membercovenantpath.viewer.data.AuthRepository().currentEmail ?: ""
