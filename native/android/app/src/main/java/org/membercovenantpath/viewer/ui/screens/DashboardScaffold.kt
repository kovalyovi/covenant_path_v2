package org.membercovenantpath.viewer.ui.screens

import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AdminPanelSettings
import androidx.compose.material.icons.filled.ArrowDropDown
import androidx.compose.material.icons.filled.Checklist
import androidx.compose.material.icons.filled.EventAvailable
import androidx.compose.material.icons.filled.GridOn
import androidx.compose.material.icons.filled.Insights
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.PersonAddAlt
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Sync
import androidx.compose.material.icons.filled.Timelapse
import androidx.compose.material.icons.filled.WaterDrop
import androidx.compose.material.icons.outlined.Summarize
import androidx.compose.material3.CenterAlignedTopAppBar
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject
import org.membercovenantpath.viewer.data.AppConfig
import org.membercovenantpath.viewer.data.EnrollmentStatus
import org.membercovenantpath.viewer.model.Member
import org.membercovenantpath.viewer.model.Stake
import org.membercovenantpath.viewer.ui.components.ConfirmDialog
import org.membercovenantpath.viewer.ui.components.FreshnessChip
import org.membercovenantpath.viewer.ui.components.GoldenHourSkeleton
import org.membercovenantpath.viewer.ui.components.KpiSkeleton
import org.membercovenantpath.viewer.ui.components.MemberListSkeleton
import org.membercovenantpath.viewer.ui.components.ReauthDialog
import org.membercovenantpath.viewer.ui.components.StaleCredentialBanner
import org.membercovenantpath.viewer.ui.components.SyncingBanner
import org.membercovenantpath.viewer.ui.screens.tabs.BaptismsScreen
import org.membercovenantpath.viewer.ui.screens.tabs.GoldenHourScreen
import org.membercovenantpath.viewer.ui.screens.tabs.KpisScreen
import org.membercovenantpath.viewer.ui.screens.tabs.NeedsScreen
import org.membercovenantpath.viewer.ui.screens.tabs.TableScreen
import org.membercovenantpath.viewer.ui.theme.TabColors
import org.membercovenantpath.viewer.viewmodel.ActionsViewModel
import org.membercovenantpath.viewer.viewmodel.DashboardUiState
import org.membercovenantpath.viewer.viewmodel.DashboardViewModel
import org.membercovenantpath.viewer.viewmodel.LoadState

/** The five tabs, each with its own accent (mirrors dashboard_page.dart `_tabs`). "By Month" is no
 *  longer its own tab — the baptisms-by-month chart now lives at the bottom of KPIs (#1). */
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
    dashVm: DashboardViewModel,
    actionsVm: ActionsViewModel,
    onOpenMember: (Member) -> Unit,
    onSignOut: () -> Unit,
    onOpenSettings: () -> Unit,
    onOpenInvite: () -> Unit,
    onOpenAdmin: () -> Unit,
) {
    var tab by remember { mutableStateOf(DashboardTab.Baptisms) }
    val snackbar = remember { SnackbarHostState() }
    val scope = rememberCoroutineScope()
    val context = androidx.compose.ui.platform.LocalContext.current
    fun toast(m: String) = scope.launch { snackbar.showSnackbar(m) }

    // One-time post-login passkey upsell (#25), only where passkeys work.
    androidx.compose.runtime.LaunchedEffect(Unit) {
        dashVm.maybeSuggestPasskey {
            scope.launch {
                val res = snackbar.showSnackbar(
                    message = "Tip: add a passkey to sign in without a password next time.",
                    actionLabel = "Add passkey",
                )
                if (res == androidx.compose.material3.SnackbarResult.ActionPerformed) {
                    actionsVm.addPasskey(context) { _, msg -> toast(msg) }
                }
            }
        }
    }

    var showSync by remember { mutableStateOf(false) }
    var syncStatus by remember { mutableStateOf<EnrollmentStatus?>(null) }
    var syncLoading by remember { mutableStateOf(true) }
    var report by remember { mutableStateOf<JsonObject?>(null) }
    var reportBuilding by remember { mutableStateOf(false) }
    var revokeConfirm by remember { mutableStateOf(false) }
    var showReauth by remember { mutableStateOf(false) }

    // In-app re-auth modal (port of web `openReauth`) — never bounce a signed-in user back to the
    // login screen. Falls back to sign-out only when the broker isn't configured.
    fun openReauth() {
        if (AppConfig.brokerAvailable) showReauth = true else onSignOut()
    }

    fun openSync() {
        if (!AppConfig.brokerAvailable) { toast("Sync settings require Church account login."); return }
        syncLoading = true
        showSync = true
        dashVm.ensureEnrollStatus { s -> syncStatus = s; syncLoading = false }
    }

    fun syncNow() {
        dashVm.syncNow { ok, info ->
            toast(
                if (!ok) "Couldn't start sync: $info"
                else if (info == "partial") "Sync started — your calling can't pull every field, so some data stays blank. Takes a few minutes."
                else "Sync started for your stake — this takes a few minutes.",
            )
        }
    }

    fun generateReport() {
        if (!AppConfig.brokerAvailable) { toast("Reports need Church-account login configured."); return }
        reportBuilding = true
        actionsVm.report(
            onReport = { reportBuilding = false; report = it },
            onError = { reportBuilding = false; toast(it) },
        )
    }

    Scaffold(
        topBar = {
            CenterAlignedTopAppBar(
                title = {
                    StakeTitle(state.stakes, state.currentStakeId, state.stakeName ?: "Covenant Path", dashVm::switchStake)
                },
                actions = {
                    state.lastSyncedAt?.let {
                        FreshnessChip(
                            iso = it,
                            compact = true,
                            syncing = state.syncing,
                            onSyncNow = if (AppConfig.brokerAvailable) ({ syncNow() }) else null,
                        )
                    }
                    IconButton(onClick = dashVm::refresh) { Icon(Icons.Filled.Refresh, contentDescription = "Refresh") }
                    OverflowMenu(
                        isAdmin = state.isAdmin,
                        onSync = { openSync() },
                        onReport = { generateReport() },
                        onInvite = onOpenInvite,
                        onAdmin = onOpenAdmin,
                        onSettings = onOpenSettings,
                    )
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
        snackbarHost = { SnackbarHost(snackbar) },
    ) { padding ->
        Column(Modifier.fillMaxSize().padding(padding)) {
            if (state.syncing) SyncingBanner(state.syncStartedAt)
            if (state.staleCredential) {
                StaleCredentialBanner(
                    state = state.enrollStatus?.credential?.state ?: "revoked",
                    isProvider = state.enrollStatus?.credential?.isProvider == true,
                    lastError = state.enrollStatus?.credential?.lastError,
                    onReenroll = { openReauth() },
                )
            }

            // N6: breathing room so the last card/row isn't flush against the bottom nav bar
            // (the Scaffold already insets by the nav height under edge-to-edge; this just adds a gap).
            Box(Modifier.fillMaxWidth().weight(1f).padding(bottom = 12.dp)) {
                when (val load = state.load) {
                    // Per-tab content-shaped skeleton (N8) so Golden Hour / KPIs don't flash member rows.
                    is LoadState.Loading -> when (tab) {
                        DashboardTab.GoldenHour -> GoldenHourSkeleton()
                        DashboardTab.Kpis -> KpiSkeleton()
                        else -> MemberListSkeleton()
                    }
                    is LoadState.Error -> CenteredError(load.message, onRetry = dashVm::refresh)
                    LoadState.Ready -> {
                        val members = state.members
                        if (members.isEmpty() && tab != DashboardTab.Kpis) {
                            EnrollmentEmptyState(state.enrollStatus, brokerAvailable = AppConfig.brokerAvailable, onAuthorize = { openReauth() })
                        } else {
                            // Notes ride a CompositionLocal so every list row (MemberRow, the
                            // baptisms timeline, the table) can show its note line without props.
                            androidx.compose.runtime.CompositionLocalProvider(
                                org.membercovenantpath.viewer.ui.components.LocalMemberNotes provides state.notes,
                            ) {
                                when (tab) {
                                    DashboardTab.Baptisms -> BaptismsScreen(members, state.missionariesByUnit, onOpenMember)
                                    DashboardTab.GoldenHour -> GoldenHourScreen(members, onOpenMember)
                                    DashboardTab.Needs -> NeedsScreen(members, onOpenMember)
                                    DashboardTab.Kpis -> KpisScreen(members, onOpenMember)
                                    DashboardTab.Table -> TableScreen(members, onOpenMember)
                                }
                            }
                        }
                    }
                }
                if (reportBuilding) {
                    Box(Modifier.fillMaxSize(), contentAlignment = androidx.compose.ui.Alignment.Center) {
                        androidx.compose.material3.CircularProgressIndicator()
                    }
                }
            }
        }
    }

    if (showSync) {
        SyncSettingsSheet(
            status = syncStatus,
            loading = syncLoading,
            onSyncNow = { syncNow() },
            onRevoke = { revokeConfirm = true },
            onDismiss = { showSync = false },
        )
    }
    if (revokeConfirm) {
        ConfirmDialog(
            title = "Revoke sync access?",
            message = "Daily sync for your stake will stop. Re-enroll anytime by signing in again.",
            confirmLabel = "Revoke",
            onConfirm = { dashVm.revoke { ok, info -> toast(if (ok) "Sync access revoked." else "Could not revoke: $info") } },
            onDismiss = { revokeConfirm = false },
        )
    }
    report?.let { rep ->
        ReportSheet(report = rep, onEmail = { actionsVm.emailReport { _, msg -> toast(msg) } }, onDismiss = { report = null })
    }
    if (showReauth) {
        ReauthDialog(
            onDismiss = { showReauth = false },
            onSuccess = { msg ->
                showReauth = false
                toast(msg)
                dashVm.reloadEnrollStatus()
            },
        )
    }
}

/** App-bar title that doubles as a stake switcher for multi-stake power users. */
@Composable
private fun StakeTitle(stakes: List<Stake>, currentId: String?, fallback: String, onSelect: (String) -> Unit) {
    // Stake names are long (e.g. Cyrillic district names) and the centered app-bar title is narrow,
    // so allow up to 2 lines at a slightly smaller size instead of clipping to one ellipsized line.
    if (stakes.size < 2) {
        Text(
            fallback,
            style = MaterialTheme.typography.titleSmall,
            maxLines = 2,
            overflow = TextOverflow.Ellipsis,
            textAlign = TextAlign.Center,
        )
        return
    }
    var open by remember { mutableStateOf(false) }
    TextButton(onClick = { open = true }) {
        Text(
            fallback,
            style = MaterialTheme.typography.titleSmall,
            maxLines = 2,
            overflow = TextOverflow.Ellipsis,
            textAlign = TextAlign.Center,
            modifier = Modifier.weight(1f, fill = false),
        )
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
private fun OverflowMenu(
    isAdmin: Boolean,
    onSync: () -> Unit,
    onReport: () -> Unit,
    onInvite: () -> Unit,
    onAdmin: () -> Unit,
    onSettings: () -> Unit,
) {
    var open by remember { mutableStateOf(false) }
    IconButton(onClick = { open = true }) { Icon(Icons.Filled.MoreVert, contentDescription = "Menu") }
    DropdownMenu(expanded = open, onDismissRequest = { open = false }) {
        DropdownMenuItem(
            text = { Text("Sync settings") },
            leadingIcon = { Icon(Icons.Filled.Sync, contentDescription = null) },
            onClick = { open = false; onSync() },
        )
        DropdownMenuItem(
            text = { Text("Generate report") },
            leadingIcon = { Icon(Icons.Outlined.Summarize, contentDescription = null) },
            onClick = { open = false; onReport() },
        )
        DropdownMenuItem(
            text = { Text("Invite a power user") },
            leadingIcon = { Icon(Icons.Filled.PersonAddAlt, contentDescription = null) },
            onClick = { open = false; onInvite() },
        )
        if (isAdmin) {
            DropdownMenuItem(
                text = { Text("Admin · Ops console") },
                leadingIcon = { Icon(Icons.Filled.AdminPanelSettings, contentDescription = null) },
                onClick = { open = false; onAdmin() },
            )
        }
        DropdownMenuItem(
            text = { Text("Settings") },
            leadingIcon = { Icon(Icons.Filled.Settings, contentDescription = null) },
            onClick = { open = false; onSettings() },
        )
    }
}
