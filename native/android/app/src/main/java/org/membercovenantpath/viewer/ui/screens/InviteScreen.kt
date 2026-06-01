package org.membercovenantpath.viewer.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.PersonOff
import androidx.compose.material.icons.filled.ArrowDropDown
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.ListItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import org.membercovenantpath.viewer.ui.components.CardSkeleton
import org.membercovenantpath.viewer.viewmodel.AppViewModelFactory
import org.membercovenantpath.viewer.viewmodel.InviteViewModel

/**
 * Power users (#23): give someone your exact access. They sign in with the invited email (a one-time
 * code — no Church account needed), see what you see, and can invite others. Backed by the
 * escalation-safe invite_power_user / revoke_power_user RPCs. Mirrors invite_page.dart.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun InviteScreen(onBack: () -> Unit) {
    val context = androidx.compose.ui.platform.LocalContext.current
    val vm: InviteViewModel = viewModel(factory = AppViewModelFactory(context))
    val s by vm.state.collectAsStateWithLifecycle()

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Power users") },
                navigationIcon = { IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back") } },
            )
        },
    ) { padding ->
        Column(Modifier.fillMaxSize().padding(padding)) {
            Column(Modifier.padding(16.dp)) {
                Text(
                    "Give someone your exact access. They sign in with the invited email (a one-time code " +
                        "is sent — no Church account needed), see what you see, and can invite others.",
                )
                Spacer(Modifier.size(12.dp))
                if (s.units.size > 1) {
                    UnitScopeDropdown(s.unitId, s.units, vm::setUnit)
                    Spacer(Modifier.size(12.dp))
                }
                Row(verticalAlignment = Alignment.CenterVertically) {
                    OutlinedTextField(
                        value = s.email,
                        onValueChange = vm::onEmail,
                        label = { Text("Email to invite") },
                        singleLine = true,
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email),
                        modifier = Modifier.weight(1f),
                    )
                    Spacer(Modifier.width(8.dp))
                    Button(onClick = vm::invite, enabled = !s.busy) {
                        if (s.busy) CircularProgressIndicator(strokeWidth = 2.dp, modifier = Modifier.size(18.dp))
                        else Text("Invite")
                    }
                }
                s.message?.let {
                    Text(
                        it,
                        color = if (s.ok) Color(0xFF2E7D32) else MaterialTheme.colorScheme.error,
                        style = MaterialTheme.typography.bodySmall,
                        modifier = Modifier.padding(top = 10.dp),
                    )
                }
            }
            HorizontalDivider()
            Box(Modifier.weight(1f).fillMaxSize()) {
              when {
                s.loading -> CardSkeleton(lines = 3, modifier = Modifier.padding(16.dp))
                s.byEmail.isEmpty() -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    Text("No power users invited yet.")
                }
                else -> LazyColumn {
                    items(s.byEmail, key = { it.invitedEmail ?: it.hashCode().toString() }) { r ->
                        val revoked = r.status == "revoked"
                        ListItem(
                            leadingContent = { Icon(if (revoked) Icons.Filled.PersonOff else Icons.Filled.Person, contentDescription = null) },
                            headlineContent = { Text(r.invitedEmail ?: "—") },
                            supportingContent = {
                                Text(
                                    "${r.role ?: ""} • ${r.status ?: ""}" +
                                        (r.invitedByEmail?.let { " • by $it" } ?: ""),
                                )
                            },
                            trailingContent = {
                                if (!revoked) TextButton(onClick = { r.invitedEmail?.let(vm::revoke) }) { Text("Revoke") }
                            },
                        )
                    }
                }
              }
            }
        }
    }
}

/** Scope picker (whole access vs one unit). A plain button + DropdownMenu — version-stable. */
@Composable
private fun UnitScopeDropdown(
    unitId: String?,
    units: List<org.membercovenantpath.viewer.model.Unit>,
    onSelect: (String?) -> Unit,
) {
    var expanded by remember { mutableStateOf(false) }
    val label = if (unitId == null) "Everything I can see"
    else (units.firstOrNull { it.id == unitId }?.name?.let { "$it only" } ?: "Selected unit")
    Column {
        Text("Access to", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        OutlinedButton(onClick = { expanded = true }, modifier = Modifier.fillMaxWidth()) {
            Text(label, modifier = Modifier.weight(1f))
            Icon(Icons.Filled.ArrowDropDown, contentDescription = null)
        }
        DropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
            DropdownMenuItem(text = { Text("Everything I can see") }, onClick = { onSelect(null); expanded = false })
            units.forEach { u ->
                DropdownMenuItem(text = { Text("${u.name} only") }, onClick = { onSelect(u.id); expanded = false })
            }
        }
    }
}
