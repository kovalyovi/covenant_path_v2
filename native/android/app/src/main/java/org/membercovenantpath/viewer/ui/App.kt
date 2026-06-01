package org.membercovenantpath.viewer.ui

import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import org.membercovenantpath.viewer.data.SupabaseClientProvider
import org.membercovenantpath.viewer.ui.screens.ConfigErrorScreen
import org.membercovenantpath.viewer.ui.screens.DashboardScaffold
import org.membercovenantpath.viewer.ui.screens.LoginScreen
import org.membercovenantpath.viewer.ui.screens.PersonDetailScreen
import org.membercovenantpath.viewer.ui.theme.CovenantPathTheme
import org.membercovenantpath.viewer.viewmodel.AuthGate
import org.membercovenantpath.viewer.viewmodel.AuthViewModel
import org.membercovenantpath.viewer.viewmodel.DashboardViewModel

private object Routes {
    const val LOGIN = "login"
    const val DASHBOARD = "dashboard"
    const val DETAIL = "detail/{uuid}"
    fun detail(uuid: String) = "detail/$uuid"
}

/**
 * App root: theme + auth gate + nav graph. Routes between Login and the Dashboard off the
 * Supabase session (AuthGate), with a Person Detail destination. A blank config (no
 * SUPABASE_URL/ANON_KEY) shows a config screen, mirroring the Flutter `_ConfigError`.
 */
@Composable
fun App() {
    CovenantPathTheme {
        if (!SupabaseClientProvider.isConfigured) {
            ConfigErrorScreen()
            return@CovenantPathTheme
        }

        val authVm: AuthViewModel = viewModel()
        val gate by authVm.gate.collectAsStateWithLifecycle()

        when (gate) {
            AuthGate.Loading -> org.membercovenantpath.viewer.ui.screens.CenteredLoading()
            AuthGate.SignedOut -> LoginScreen(authVm)
            AuthGate.SignedIn -> SignedInNav(onSignOut = authVm::signOut)
        }
    }
}

@Composable
private fun SignedInNav(onSignOut: () -> Unit) {
    // One DashboardViewModel scoped to the signed-in session; the detail screen reads its members
    // by uuid so we never serialize a whole Member through the back stack.
    val dashVm: DashboardViewModel = viewModel()
    val state by dashVm.state.collectAsStateWithLifecycle()
    val nav = rememberNavController()

    NavHost(navController = nav, startDestination = Routes.DASHBOARD) {
        composable(Routes.DASHBOARD) {
            DashboardScaffold(
                state = state,
                onOpenMember = { m -> m.personUuid?.let { nav.navigate(Routes.detail(it)) } },
                onRefresh = dashVm::refresh,
                onSwitchStake = dashVm::switchStake,
                onSignOut = onSignOut,
            )
        }
        composable(
            route = Routes.DETAIL,
            arguments = listOf(navArgument("uuid") { type = NavType.StringType }),
        ) { entry ->
            val uuid = entry.arguments?.getString("uuid")
            val member = state.members.firstOrNull { it.personUuid == uuid }
            if (member != null) {
                PersonDetailScreen(member = member, onBack = { nav.popBackStack() })
            } else {
                // Member list not ready (process death) — bounce back to the dashboard.
                nav.popBackStack()
            }
        }
    }
}
