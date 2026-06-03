package org.membercovenantpath.viewer.ui.screens

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Cancel
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.CloudSync
import androidx.compose.material.icons.filled.HourglassTop
import androidx.compose.material.icons.filled.LinkOff
import androidx.compose.material.icons.filled.PersonAddAlt
import androidx.compose.material.icons.filled.PhotoCamera
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.RemoveCircleOutline
import androidx.compose.material.icons.filled.Replay
import androidx.compose.material.icons.filled.Storage
import androidx.compose.material.icons.filled.Sync
import androidx.compose.material.icons.filled.TableChart
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import kotlinx.serialization.json.JsonObject
import org.membercovenantpath.viewer.data.arr
import org.membercovenantpath.viewer.data.bool
import org.membercovenantpath.viewer.data.int
import org.membercovenantpath.viewer.data.obj
import org.membercovenantpath.viewer.data.str
import org.membercovenantpath.viewer.logic.Freshness
import org.membercovenantpath.viewer.model.AppAdmin
import org.membercovenantpath.viewer.ui.components.CardSkeleton
import org.membercovenantpath.viewer.ui.components.ConfirmDialog
import org.membercovenantpath.viewer.ui.components.SectionCard
import org.membercovenantpath.viewer.viewmodel.AdminViewModel
import org.membercovenantpath.viewer.viewmodel.Panel

/**
 * Admin · Ops console (#26), admin-gated server-side. Independently-loaded panels: system health +
 * data freshness + maintenance + tool links (from /admin/summary), diagnostics (recent sync),
 * enrolled stakes (per-stake state/coverage/freshness + admin revoke + per-stake sync), GitHub
 * Actions runs (+ re-run) and changelog, and admins (invite/revoke). Mirrors admin_page.dart.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AdminScreen(onBack: () -> Unit) {
    val vm: AdminViewModel = viewModel()
    val s by vm.state.collectAsStateWithLifecycle()
    val snackbar = remember { androidx.compose.material3.SnackbarHostState() }
    val context = LocalContext.current

    LaunchedEffect(s.toast) {
        s.toast?.let { snackbar.showSnackbar(it); vm.clearToast() }
    }

    var inviteOpen by remember { mutableStateOf(false) }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Admin · Ops console") },
                navigationIcon = { IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back") } },
                actions = { IconButton(onClick = vm::loadAll, enabled = !s.busy) { Icon(Icons.Filled.Refresh, contentDescription = "Refresh") } },
            )
        },
        snackbarHost = { androidx.compose.material3.SnackbarHost(snackbar) },
    ) { padding ->
        Box(Modifier.fillMaxSize().padding(padding)) {
            LazyColumn(Modifier.fillMaxWidth(), contentPadding = androidx.compose.foundation.layout.PaddingValues(12.dp)) {
                item { PanelSection("System", s.summary) { SystemPanels(it, vm) } }
                item { PanelSection("Diagnostics", s.diagnostics) { DiagnosticsCard(it) } }
                item {
                    PanelSection("Enrolled stakes", s.stakes) {
                        EnrolledStakesCard(it, busy = s.busy, onRevoke = vm::revokeStake, onSync = vm::syncStake)
                    }
                }
                item {
                    PanelSection("GitHub Actions", s.actions, errorHint =
                        "Set GITHUB_TOKEN on the broker (Actions: read & write, Contents: read) to enable runs + the changelog. The rest of the console still works.") {
                        Column {
                            RunsCard(it, busy = s.busy, onRerun = vm::rerun, openUrl = { url -> openUrl(context, url) })
                            ChangelogCard(it, openUrl = { url -> openUrl(context, url) })
                        }
                    }
                }
                item {
                    when (val p = s.admins) {
                        is Panel.Loading -> SectionCard("Admins…") { CardSkeleton(lines = 3) }
                        is Panel.Error -> SectionCard("Admins") { Text("Couldn't load: ${p.message}", style = MaterialTheme.typography.bodySmall) }
                        is Panel.Ready -> AdminsCard(p.data, currentEmail = vm.currentEmail, onInvite = { inviteOpen = true }, onRevoke = vm::revokeAdmin)
                    }
                }
                item { Spacer(Modifier.size(24.dp)) }
            }
            if (s.busy) {
                Box(Modifier.fillMaxSize().clickable(enabled = false) {}, contentAlignment = Alignment.Center) {
                    Surface(color = Color(0x33000000), modifier = Modifier.fillMaxSize()) {}
                    CircularProgressIndicator()
                }
            }
        }
    }

    if (inviteOpen) {
        var email by remember { mutableStateOf("") }
        androidx.compose.material3.AlertDialog(
            onDismissRequest = { inviteOpen = false },
            title = { Text("Invite an admin") },
            text = {
                androidx.compose.material3.OutlinedTextField(email, { email = it }, label = { Text("Email") }, singleLine = true, modifier = Modifier.fillMaxWidth())
            },
            confirmButton = { TextButton(onClick = { inviteOpen = false; if (email.isNotBlank()) vm.inviteAdmin(email.trim()) }) { Text("Invite") } },
            dismissButton = { TextButton(onClick = { inviteOpen = false }) { Text("Cancel") } },
        )
    }
}

private fun openUrl(context: android.content.Context, url: String?) {
    if (url.isNullOrEmpty()) return
    runCatching { context.startActivity(android.content.Intent(android.content.Intent.ACTION_VIEW, android.net.Uri.parse(url))) }
}

/** A titled section that renders a skeleton while loading, a friendly error, or its content. */
@Composable
private fun PanelSection(title: String, panel: Panel<JsonObject>, errorHint: String? = null, content: @Composable (JsonObject) -> Unit) {
    when (panel) {
        is Panel.Loading -> SectionCard("$title…") { CardSkeleton(lines = 3) }
        is Panel.Error -> SectionCard(title) {
            Text("Couldn't load: ${panel.message}${errorHint?.let { "\n\n$it" } ?: ""}", style = MaterialTheme.typography.bodySmall)
        }
        is Panel.Ready -> content(panel.data)
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun SystemPanels(summary: JsonObject, vm: AdminViewModel) {
    val sb = summary.obj("supabase") ?: JsonObject(emptyMap())
    val brokerOk = summary.obj("broker")?.bool("ok") == true
    val githubConfigured = summary.bool("github_configured")
    Column {
        SectionCard("System health") {
            FlowRow(horizontalArrangement = Arrangement.spacedBy(10.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                StatusPill("Broker", brokerOk)
                StatusPill("Supabase", sb.bool("ok"))
                StatusPill("GitHub Actions", githubConfigured, offText = "not linked")
            }
        }
        SectionCard("Data freshness") {
            Column {
                KvRow("Last member update", Freshness.ago(sb.str("last_member_update")))
                KvRow("Last stake sync", Freshness.ago(sb.str("last_stake_sync")))
                HorizontalDivider(Modifier.padding(vertical = 8.dp))
                FlowRow(horizontalArrangement = Arrangement.spacedBy(18.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Stat("Members", sb.int("members"))
                    Stat("Units", sb.int("units"))
                    Stat("Stakes", sb.int("stakes"))
                    Stat("Admins", sb.int("admins"))
                }
            }
        }
        MaintenanceCard(githubConfigured, vm)
        LinksCard(summary)
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun MaintenanceCard(githubConfigured: Boolean, vm: AdminViewModel) {
    var confirm by remember { mutableStateOf<Triple<String, String, Map<String, String>>?>(null) }
    SectionCard("Maintenance") {
        Column {
            Text("Each flow re-scrapes LCR (required for fresh data); the choice controls where it writes.")
            Spacer(Modifier.size(12.dp))
            FlowRow(horizontalArrangement = Arrangement.spacedBy(10.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Button(onClick = { confirm = Triple("Full sync", "Re-scrapes LCR and repopulates both Google Sheets and Supabase.", mapOf("targets" to "both")) }, enabled = githubConfigured) {
                    Icon(Icons.Filled.CloudSync, contentDescription = null, modifier = Modifier.size(18.dp)); Text(" Full sync")
                }
                OutlinedButton(onClick = { confirm = Triple("Supabase only", "Re-scrapes LCR and repopulates Supabase (the app data) only.", mapOf("targets" to "supabase")) }, enabled = githubConfigured) {
                    Icon(Icons.Filled.Storage, contentDescription = null, modifier = Modifier.size(18.dp)); Text(" Supabase only")
                }
                OutlinedButton(onClick = { confirm = Triple("Google Sheets only", "Re-scrapes LCR and repopulates the Google Sheet only.", mapOf("targets" to "sheets")) }, enabled = githubConfigured) {
                    Icon(Icons.Filled.TableChart, contentDescription = null, modifier = Modifier.size(18.dp)); Text(" Sheets only")
                }
                OutlinedButton(onClick = { confirm = Triple("Refresh photos", "Re-scrapes LCR, updates Supabase, and refreshes member avatars.", mapOf("targets" to "supabase", "photos" to "true")) }, enabled = githubConfigured) {
                    Icon(Icons.Filled.PhotoCamera, contentDescription = null, modifier = Modifier.size(18.dp)); Text(" Refresh photos")
                }
            }
            if (!githubConfigured) {
                Text("Link GitHub (set GITHUB_TOKEN on the broker) to enable flows.", style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 8.dp))
            }
        }
    }
    confirm?.let { (label, body, inputs) ->
        ConfirmDialog(
            title = label,
            message = "$body It runs in the cloud (GitHub Actions) and takes a few minutes.",
            confirmLabel = label,
            onConfirm = { vm.dispatch(label, inputs) },
            onDismiss = { confirm = null },
        )
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun LinksCard(summary: JsonObject) {
    val links = summary.obj("links") ?: return
    if (links.isEmpty()) return
    val context = LocalContext.current
    SectionCard("Tools & dashboards") {
        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            links.forEach { (name, value) ->
                val url = value.toString().trim('"')
                androidx.compose.material3.AssistChip(onClick = { openUrl(context, url) }, label = { Text(name) })
            }
        }
    }
}

@Composable
private fun DiagnosticsCard(diag: JsonObject) {
    val runs = diag.arr("runs")
    val latestSync = runs?.firstOrNull { (it as? JsonObject)?.str("kind") == "sync" } as? JsonObject
    SectionCard("Diagnostics") {
        if (latestSync == null) {
            Text("No sync diagnostics yet.")
            return@SectionCard
        }
        val payload = latestSync.obj("payload") ?: JsonObject(emptyMap())
        val req = payload.obj("requests") ?: JsonObject(emptyMap())
        val stats = payload.obj("run_stats") ?: JsonObject(emptyMap())
        val failed = stats.arr("failed_units")?.size ?: 0
        val successPct = req.str("success_pct")?.toDoubleOrNull() ?: 100.0
        Column {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("Last run ${Freshness.ago(latestSync.str("run_at"))}", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            Spacer(Modifier.size(8.dp))
            @OptIn(ExperimentalLayoutApi::class)
            FlowRow(horizontalArrangement = Arrangement.spacedBy(10.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                StatusPill("Requests ${successPct.toInt()}%", successPct >= 99)
                StatusPill("Units ${stats.int("units")} ok", failed == 0, offText = "$failed failed")
                StatusPill("${req.int("total_errors")} request errors", req.int("total_errors") == 0)
            }
        }
    }
}

@Composable
private fun EnrolledStakesCard(
    data: JsonObject,
    busy: Boolean,
    onRevoke: (String, String) -> Unit,
    onSync: (String, String) -> Unit,
) {
    val stakes = data.arr("stakes")
    var confirm by remember { mutableStateOf<Pair<String, () -> Unit>?>(null) }
    SectionCard("Enrolled stakes${stakes?.let { " (${it.size})" } ?: ""}") {
        if (stakes == null || stakes.isEmpty()) {
            Text("No stakes yet.")
            return@SectionCard
        }
        Column {
            stakes.forEach { el ->
                val st = el as? JsonObject ?: return@forEach
                val cred = st.obj("credential")
                val name = st.str("name") ?: "—"
                val stakeId = st.str("stake_id") ?: ""
                val members = st.int("member_count")
                val running = st.str("sync_state") == "running"
                val (credLabel, credColor) = credBadge(cred)
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    Text(name, fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
                    if (running) CircularProgressIndicator(strokeWidth = 2.dp, modifier = Modifier.size(14.dp))
                    if (!running && cred?.str("state") == "active") {
                        IconButton(onClick = { confirm = "Sync $name now?" to { onSync(st.str("unit_number") ?: "", name) } }, enabled = !busy) {
                            Icon(Icons.Filled.Sync, contentDescription = "Sync this stake", modifier = Modifier.size(18.dp))
                        }
                        IconButton(onClick = { confirm = "Revoke sync for $name?" to { onRevoke(stakeId, name) } }, enabled = !busy) {
                            Icon(Icons.Filled.LinkOff, contentDescription = "Revoke sync", modifier = Modifier.size(18.dp))
                        }
                    }
                }
                @OptIn(ExperimentalLayoutApi::class)
                FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Tag(credLabel, credColor)
                    Text("$members members", style = MaterialTheme.typography.bodySmall)
                    Text("· synced ${Freshness.ago(st.str("last_synced_at"))}", style = MaterialTheme.typography.bodySmall)
                    cred?.str("principal_name")?.let { Text("· by $it", style = MaterialTheme.typography.bodySmall) }
                }
                HorizontalDivider(Modifier.padding(vertical = 8.dp))
            }
        }
    }
    confirm?.let { (title, action) ->
        ConfirmDialog(title = title, message = "Runs in the cloud (GitHub Actions) and takes a few minutes.", confirmLabel = "OK",
            onConfirm = action, onDismiss = { confirm = null })
    }
}

private fun credBadge(cred: JsonObject?): Pair<String, Color> = when {
    cred == null -> "No credential" to Color(0xFF9E9E9E)
    cred.str("state") == "revoked" -> "Revoked" to Color(0xFFEF6C00)
    cred.bool("complete") -> "Active · full coverage" to Color(0xFF2E7D32)
    else -> "Active · partial" to Color(0xFF1565C0)
}

@Composable
private fun RunsCard(actions: JsonObject, busy: Boolean, onRerun: (Long) -> Unit, openUrl: (String?) -> Unit) {
    if (!actions.bool("configured")) return
    val runs = actions.arr("runs")
    SectionCard("Recent Actions runs") {
        if (runs == null || runs.isEmpty()) { Text("No runs found."); return@SectionCard }
        Column {
            runs.forEach { el ->
                val r = el as? JsonObject ?: return@forEach
                val status = r.str("status") ?: ""
                val conclusion = r.str("conclusion") ?: ""
                val inProgress = status == "in_progress" || status == "queued"
                Row(Modifier.fillMaxWidth().clickable { openUrl(r.str("html_url")) }.padding(vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                    RunStatusIcon(status, conclusion)
                    Spacer(Modifier.width(10.dp))
                    Column(Modifier.weight(1f)) {
                        Text("${r.str("name")} #${r.int("run_number")}")
                        val d = Freshness.dur(r.str("duration_seconds"))
                        val dLabel = if (d.isEmpty()) "" else " · ${if (status == "completed") "took" else "running"} $d"
                        Text("${r.str("event")} · ${Freshness.ago(r.str("created_at"))}$dLabel", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    if (!inProgress) {
                        IconButton(onClick = { (r["id"]?.toString()?.toLongOrNull())?.let(onRerun) }, enabled = !busy) {
                            Icon(Icons.Filled.Replay, contentDescription = "Re-run")
                        }
                    } else {
                        CircularProgressIndicator(strokeWidth = 2.dp, modifier = Modifier.size(18.dp))
                    }
                }
            }
        }
    }
}

@Composable
private fun RunStatusIcon(status: String, conclusion: String) {
    if (status != "completed") {
        Icon(Icons.Filled.HourglassTop, contentDescription = null, tint = Color(0xFF1E88E5))
        return
    }
    val ok = conclusion == "success"
    Icon(if (ok) Icons.Filled.CheckCircle else Icons.Filled.Cancel, contentDescription = null, tint = if (ok) Color(0xFF43A047) else Color(0xFFE53935))
}

@Composable
private fun ChangelogCard(actions: JsonObject, openUrl: (String?) -> Unit) {
    if (!actions.bool("configured")) return
    val commits = actions.arr("commits")
    if (commits == null || commits.isEmpty()) return
    SectionCard("Changelog") {
        Column {
            commits.forEach { el ->
                val c = el as? JsonObject ?: return@forEach
                Column(Modifier.fillMaxWidth().clickable { openUrl(c.str("html_url")) }.padding(vertical = 6.dp)) {
                    Text(c.str("message") ?: "", maxLines = 2)
                    Text("${c.str("sha")} · ${c.str("author") ?: ""} · ${Freshness.ago(c.str("date"))}", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        }
    }
}

@Composable
private fun AdminsCard(admins: List<AppAdmin>, currentEmail: String?, onInvite: () -> Unit, onRevoke: (String) -> Unit) {
    val me = currentEmail?.lowercase()
    SectionCard("Admins", trailing = {
        TextButton(onClick = onInvite) { Icon(Icons.Filled.PersonAddAlt, contentDescription = null, modifier = Modifier.size(18.dp)); Text(" Invite") }
    }) {
        Column {
            admins.forEach { a ->
                Row(Modifier.fillMaxWidth().padding(vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text(a.email ?: "—")
                        a.invitedByEmail?.let { Text("invited by $it", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant) }
                    }
                    if (a.email?.lowercase() == me) {
                        Text("you", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.primary)
                    } else {
                        IconButton(onClick = { a.email?.let(onRevoke) }) { Icon(Icons.Filled.RemoveCircleOutline, contentDescription = "Revoke") }
                    }
                }
            }
        }
    }
}

@Composable
private fun StatusPill(label: String, ok: Boolean, offText: String? = null) {
    val color = if (ok) Color(0xFF2E7D32) else Color(0xFFEF6C00)
    Surface(color = color.copy(alpha = 0.12f), shape = androidx.compose.foundation.shape.RoundedCornerShape(20.dp)) {
        Row(Modifier.padding(horizontal = 10.dp, vertical = 5.dp), verticalAlignment = Alignment.CenterVertically) {
            Icon(if (ok) Icons.Filled.CheckCircle else Icons.Filled.Cancel, contentDescription = null, tint = color, modifier = Modifier.size(14.dp))
            Spacer(Modifier.width(5.dp))
            Text(if (ok) label else (offText ?: label), color = color, style = MaterialTheme.typography.bodySmall, fontWeight = FontWeight.Medium)
        }
    }
}

@Composable
private fun Tag(text: String, color: Color) {
    Surface(color = color.copy(alpha = 0.14f), shape = androidx.compose.foundation.shape.RoundedCornerShape(20.dp)) {
        Text(text, color = color, style = MaterialTheme.typography.bodySmall, fontWeight = FontWeight.Medium, modifier = Modifier.padding(horizontal = 9.dp, vertical = 3.dp))
    }
}

@Composable
private fun KvRow(k: String, v: String) {
    Row(Modifier.fillMaxWidth().padding(vertical = 3.dp)) {
        Text(k, modifier = Modifier.weight(1f))
        Text(v, fontWeight = FontWeight.Medium)
    }
}

@Composable
private fun Stat(label: String, value: Int) {
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Text("$value", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
        Text(label, style = MaterialTheme.typography.bodySmall)
    }
}
