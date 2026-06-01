package org.membercovenantpath.viewer.ui.screens

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowDropDown
import androidx.compose.material.icons.filled.Checklist
import androidx.compose.material.icons.filled.EventAvailable
import androidx.compose.material.icons.filled.GridOn
import androidx.compose.material.icons.filled.Insights
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Timelapse
import androidx.compose.material3.CenterAlignedTopAppBar
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.style.TextOverflow
import org.membercovenantpath.viewer.model.Member
import org.membercovenantpath.viewer.model.Stake
import org.membercovenantpath.viewer.ui.screens.tabs.BaptismsScreen
import org.membercovenantpath.viewer.ui.screens.tabs.GoldenHourScreen
import org.membercovenantpath.viewer.ui.screens.tabs.KpisScreen
import org.membercovenantpath.viewer.ui.screens.tabs.NeedsScreen
import org.membercovenantpath.viewer.ui.screens.tabs.TableScreen
import org.membercovenantpath.viewer.ui.theme.TabColors
import org.membercovenantpath.viewer.viewmodel.DashboardUiState
import org.membercovenantpath.viewer.viewmodel.LoadState

/** The five tabs, each with its own accent (mirrors dashboard_page.dart `_tabs`). */
enum class DashboardTab(val label: String, val icon: ImageVector, val color: Color) {
    Baptisms("Baptisms", Icons.Filled.EventAvailable, TabColors.Baptisms),
    GoldenHour("Golden Hour", Icons.Filled.Timelapse, TabColors.GoldenHour),
    Needs("Needs", Icons.Filled.Checklist, TabColors.Needs),
    Kpis("KPIs", Icons.Filled.Insights, TabColors.Kpis),
    Table("Table", Icons.Filled.GridOn, TabColors.Table),
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DashboardScaffold(
    state: DashboardUiState,
    onOpenMember: (Member) -> Unit,
    onRefresh: () -> Unit,
    onSwitchStake: (String) -> Unit,
    onSignOut: () -> Unit,
) {
    var tab by remember { mutableStateOf(DashboardTab.Baptisms) }

    Scaffold(
        topBar = {
            CenterAlignedTopAppBar(
                title = {
                    StakeTitle(
                        stakes = state.stakes,
                        currentId = state.currentStakeId,
                        fallback = state.stakeName ?: "Covenant Path",
                        onSelect = onSwitchStake,
                    )
                },
                actions = {
                    IconButton(onClick = onRefresh) {
                        Icon(Icons.Filled.Refresh, contentDescription = "Refresh")
                    }
                    OverflowMenu(onSignOut = onSignOut)
                },
            )
        },
        bottomBar = {
            NavigationBar {
                DashboardTab.entries.forEach { t ->
                    NavigationBarItem(
                        selected = tab == t,
                        onClick = { tab = t },
                        icon = { Icon(t.icon, contentDescription = t.label) },
                        label = { Text(t.label, maxLines = 1, overflow = TextOverflow.Ellipsis) },
                        colors = NavigationBarItemDefaults.colors(
                            selectedIconColor = t.color,
                            selectedTextColor = t.color,
                            indicatorColor = t.color.copy(alpha = 0.16f),
                        ),
                    )
                }
            }
        },
    ) { padding ->
        Box(Modifier.fillMaxSize().padding(padding)) {
            when (val load = state.load) {
                is LoadState.Loading -> CenteredLoading()
                is LoadState.Error -> CenteredError(load.message, onRetry = onRefresh)
                LoadState.Ready -> {
                    val members = state.members
                    if (members.isEmpty() && tab != DashboardTab.Kpis) {
                        EmptyMembers()
                    } else {
                        when (tab) {
                            DashboardTab.Baptisms -> BaptismsScreen(members, state.missionariesByUnit, onOpenMember)
                            DashboardTab.GoldenHour -> GoldenHourScreen(members, onOpenMember)
                            DashboardTab.Needs -> NeedsScreen(members, onOpenMember)
                            DashboardTab.Kpis -> KpisScreen(members)
                            DashboardTab.Table -> TableScreen(members, onOpenMember)
                        }
                    }
                }
            }
        }
    }
}

/** App-bar title that doubles as a stake switcher for multi-stake power users. */
@Composable
private fun StakeTitle(
    stakes: List<Stake>,
    currentId: String?,
    fallback: String,
    onSelect: (String) -> Unit,
) {
    if (stakes.size < 2) {
        Text(fallback, maxLines = 1, overflow = TextOverflow.Ellipsis)
        return
    }
    var open by remember { mutableStateOf(false) }
    TextButton(onClick = { open = true }) {
        Text(fallback, maxLines = 1, overflow = TextOverflow.Ellipsis)
        Icon(Icons.Filled.ArrowDropDown, contentDescription = "Switch stake")
    }
    DropdownMenu(expanded = open, onDismissRequest = { open = false }) {
        stakes.forEach { s ->
            DropdownMenuItem(
                text = { Text((s.name ?: "—") + if (s.id == currentId) "  ✓" else "") },
                onClick = { open = false; onSelect(s.id) },
            )
        }
    }
}

@Composable
private fun OverflowMenu(onSignOut: () -> Unit) {
    var open by remember { mutableStateOf(false) }
    IconButton(onClick = { open = true }) {
        Icon(Icons.Filled.MoreVert, contentDescription = "Menu")
    }
    DropdownMenu(expanded = open, onDismissRequest = { open = false }) {
        DropdownMenuItem(text = { Text("Sign out") }, onClick = { open = false; onSignOut() })
    }
}
