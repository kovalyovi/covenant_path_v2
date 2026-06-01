package org.membercovenantpath.viewer.ui.screens

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AddToDrive
import androidx.compose.material.icons.filled.ArrowDropDown
import androidx.compose.material.icons.filled.LinkOff
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Schedule
import androidx.compose.material.icons.filled.Sync
import androidx.compose.material.icons.filled.TableView
import androidx.compose.material.icons.filled.WarningAmber
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import org.membercovenantpath.viewer.data.EnrollmentStatus
import org.membercovenantpath.viewer.logic.Freshness
import org.membercovenantpath.viewer.ui.components.CardSkeleton
import org.membercovenantpath.viewer.viewmodel.SyncSettingsViewModel

/**
 * Sync settings (#21): stake / last synced / members / credential status; "Sync my stake now" +
 * "Revoke" (provider); a Schedule section (daily ET hour + Pause/Resume) and a Google Drive section
 * (connect/disconnect, sheet link, last refreshed, needs-reconnect). Mirrors `_SyncSettingsSheet`.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SyncSettingsSheet(
    status: EnrollmentStatus?,
    loading: Boolean,
    onSyncNow: () -> Unit,
    onRevoke: () -> Unit,
    onDismiss: () -> Unit,
) {
    val context = androidx.compose.ui.platform.LocalContext.current
    val vm: SyncSettingsViewModel = viewModel()
    val schedule by vm.schedule.collectAsStateWithLifecycle()
    val drive by vm.drive.collectAsStateWithLifecycle()
    val cred = status?.credential
    val isProvider = cred?.isProvider == true

    LaunchedEffect(isProvider) {
        if (isProvider) vm.loadSchedule()
        vm.loadDrive()
    }

    ModalBottomSheet(onDismissRequest = onDismiss) {
        Column(Modifier.padding(horizontal = 24.dp).padding(bottom = 32.dp).verticalScroll(rememberScrollState())) {
            Text("Sync settings", style = MaterialTheme.typography.titleLarge)
            Spacer(Modifier.size(16.dp))

            if (loading) {
                CardSkeleton(lines = 4)
                return@Column
            }
            if (status == null) {
                Text("Could not load sync settings — close and try again.")
                return@Column
            }

            KeyRow("Stake", status.stakeName ?: "—")
            KeyRow("Last synced", status.lastSyncedAt?.let { Freshness.exactLocal(it) } ?: "Never")
            KeyRow("Members", "${status.memberCount}")
            HorizontalDivider(Modifier.padding(vertical = 12.dp))

            if (cred == null || cred.isNone) {
                Row(verticalAlignment = Alignment.Top) {
                    Icon(Icons.Filled.WarningAmber, contentDescription = null, tint = Color(0xFFEF6C00))
                    Spacer(Modifier.width(10.dp))
                    Column {
                        Text("No sync credential", fontWeight = FontWeight.SemiBold)
                        Text("Sign in with your Church account to enable daily updates.", style = MaterialTheme.typography.bodySmall)
                    }
                }
            } else {
                KeyRow("Status", if (cred.isRevoked) "Revoked" else "Active", if (cred.isRevoked) Color(0xFFEF6C00) else Color(0xFF2E7D32))
                cred.principalName?.let { KeyRow("Provided by", it) }
                cred.enrolledAt?.let { KeyRow("Enrolled", Freshness.exactLocal(it)) }
                KeyRow("Coverage", if (cred.complete) "Complete" else "Partial")
            }
            Spacer(Modifier.size(8.dp))
            Text("Credentials are encrypted and stored server-side. Your password is never stored.", style = MaterialTheme.typography.bodySmall)

            if (isProvider) {
                Spacer(Modifier.size(16.dp))
                FilledTonalButton(onClick = { onDismiss(); onSyncNow() }, modifier = Modifier.fillMaxWidth()) {
                    Icon(Icons.Filled.Sync, contentDescription = null, modifier = Modifier.size(18.dp))
                    Text("  Sync my stake now")
                }
                Spacer(Modifier.size(8.dp))
                OutlinedButton(onClick = { onDismiss(); onRevoke() }, modifier = Modifier.fillMaxWidth()) {
                    Icon(Icons.Filled.LinkOff, contentDescription = null, modifier = Modifier.size(18.dp))
                    Text("  Revoke my sync access")
                }
                ScheduleSection(schedule, vm)
            }
            GoogleDriveSection(drive, vm, onOpenUrl = { url ->
                runCatching { context.startActivity(android.content.Intent(android.content.Intent.ACTION_VIEW, android.net.Uri.parse(url))) }
            })
        }
    }
}

@Composable
private fun KeyRow(label: String, value: String, color: Color? = null) {
    Row(Modifier.fillMaxWidth().padding(vertical = 4.dp)) {
        Text(label, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.width(110.dp))
        Text(value, color = color ?: Color.Unspecified, fontWeight = if (color != null) FontWeight.Medium else FontWeight.Normal, modifier = Modifier.weight(1f))
    }
}

@Composable
private fun ScheduleSection(s: org.membercovenantpath.viewer.viewmodel.ScheduleState, vm: SyncSettingsViewModel) {
    if (!s.loaded || !s.eligible) return
    var menuOpen by remember { mutableStateOf(false) }
    fun label(h: Int): String {
        val ampm = if (h < 12) "AM" else "PM"; val h12 = if (h % 12 == 0) 12 else h % 12
        return "$h12:00 $ampm ET"
    }
    HorizontalDivider(Modifier.padding(vertical = 16.dp))
    Row(verticalAlignment = Alignment.CenterVertically) {
        Icon(Icons.Filled.Schedule, contentDescription = null, tint = MaterialTheme.colorScheme.primary, modifier = Modifier.size(18.dp))
        Spacer(Modifier.width(8.dp))
        Text("Daily sync time", style = MaterialTheme.typography.titleSmall)
    }
    Spacer(Modifier.size(4.dp))
    Text(
        if (s.paused) "Automatic daily sync is paused. You can still \"Sync my stake now\" anytime."
        else "Your stake syncs automatically each day at this time.",
        style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
    )
    Spacer(Modifier.size(8.dp))
    Row(verticalAlignment = Alignment.CenterVertically) {
        OutlinedButton(onClick = { if (!s.paused) menuOpen = true }, enabled = !s.busy && !s.paused) {
            Text(label(s.hourEt))
            Icon(Icons.Filled.ArrowDropDown, contentDescription = null)
        }
        DropdownMenu(expanded = menuOpen, onDismissRequest = { menuOpen = false }) {
            (0..23).forEach { h -> DropdownMenuItem(text = { Text(label(h)) }, onClick = { menuOpen = false; vm.saveSchedule(hour = h) }) }
        }
        Spacer(Modifier.weight(1f))
        if (s.busy) CircularProgressIndicator(strokeWidth = 2.dp, modifier = Modifier.size(16.dp))
        else TextButton(onClick = { vm.saveSchedule(paused = !s.paused) }) {
            Icon(if (s.paused) Icons.Filled.PlayArrow else Icons.Filled.Pause, contentDescription = null, modifier = Modifier.size(18.dp))
            Text(if (s.paused) " Resume" else " Pause")
        }
    }
}

@Composable
private fun GoogleDriveSection(
    d: org.membercovenantpath.viewer.viewmodel.DriveState,
    vm: SyncSettingsViewModel,
    onOpenUrl: (String) -> Unit,
) {
    if (!d.loaded || !d.eligible) return
    HorizontalDivider(Modifier.padding(vertical = 16.dp))
    Row(verticalAlignment = Alignment.CenterVertically) {
        Icon(Icons.Filled.AddToDrive, contentDescription = null, tint = MaterialTheme.colorScheme.primary, modifier = Modifier.size(18.dp))
        Spacer(Modifier.width(8.dp))
        Text("Google Drive", style = MaterialTheme.typography.titleSmall)
    }
    Spacer(Modifier.size(4.dp))

    if (!d.configured) {
        Text(
            "Drive integration isn't enabled on the server yet — your stake's sheet is kept on the shared service account for now.",
            style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        return
    }

    if (d.needsReconnect) {
        Row(verticalAlignment = Alignment.Top) {
            Icon(Icons.Filled.WarningAmber, contentDescription = null, tint = Color(0xFFEF6C00), modifier = Modifier.size(15.dp))
            Spacer(Modifier.width(6.dp))
            Text(
                "Google Drive needs reconnecting — the saved access expired, so syncs are using the shared sheet for now. Reconnect to resume writing to your own Drive.",
                style = MaterialTheme.typography.bodySmall, color = Color(0xFFEF6C00),
            )
        }
    } else {
        Text(
            if (d.connected) "Connected as ${d.email ?: ""}. Your stake's spreadsheet lives in your Drive."
            else "Connect your Google account so your stake gets its own spreadsheet that you own (the app can only touch the file it creates).",
            style = MaterialTheme.typography.bodySmall,
        )
    }

    if (d.connected && d.sheetUrl != null) {
        Spacer(Modifier.size(6.dp))
        Row(
            Modifier.clickable { onOpenUrl(d.sheetUrl) },
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(Icons.Filled.TableView, contentDescription = null, modifier = Modifier.size(16.dp))
            Spacer(Modifier.width(6.dp))
            Text("Open your stake spreadsheet", color = MaterialTheme.colorScheme.primary, style = MaterialTheme.typography.bodySmall)
        }
    }
    d.lastSyncedAt?.takeIf { d.connected }?.let {
        Spacer(Modifier.size(4.dp))
        Text("Sheet last refreshed ${Freshness.exactLocal(it)}.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }

    Spacer(Modifier.size(8.dp))
    Row(verticalAlignment = Alignment.CenterVertically) {
        if (!d.connected) {
            FilledTonalButton(onClick = { vm.connectDrive { url -> if (url != null) onOpenUrl(url) } }, enabled = !d.busy) {
                Icon(Icons.Filled.AddToDrive, contentDescription = null, modifier = Modifier.size(18.dp))
                Text("  Connect Google Drive")
            }
        } else {
            OutlinedButton(onClick = vm::disconnectDrive, enabled = !d.busy) {
                Icon(Icons.Filled.LinkOff, contentDescription = null, modifier = Modifier.size(18.dp))
                Text("  Disconnect")
            }
        }
        Spacer(Modifier.width(8.dp))
        TextButton(onClick = vm::loadDrive) { Text("Refresh") }
    }
}
