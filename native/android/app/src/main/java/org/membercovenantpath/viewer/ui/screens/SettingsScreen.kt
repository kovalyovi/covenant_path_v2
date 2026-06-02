package org.membercovenantpath.viewer.ui.screens

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.Logout
import androidx.compose.material.icons.filled.AccountCircle
import androidx.compose.material.icons.filled.Brightness6
import androidx.compose.material.icons.filled.Fingerprint
import androidx.compose.material.icons.filled.Key
import androidx.compose.material.icons.filled.SupportAgent
import androidx.compose.material.icons.outlined.Feedback
import androidx.compose.material.icons.outlined.Info
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.ListItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.fragment.app.FragmentActivity
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import kotlinx.coroutines.launch
import org.membercovenantpath.viewer.data.AppConfig
import org.membercovenantpath.viewer.ui.AppBiometric
import org.membercovenantpath.viewer.ui.components.AboutDialog
import org.membercovenantpath.viewer.ui.components.RulesDialog
import org.membercovenantpath.viewer.ui.components.ContactDialog
import org.membercovenantpath.viewer.ui.components.FeedbackDialog
import org.membercovenantpath.viewer.viewmodel.ActionsViewModel
import org.membercovenantpath.viewer.viewmodel.AppLockViewModel
import org.membercovenantpath.viewer.viewmodel.ThemeViewModel

/**
 * Grouped Settings (#24): Appearance (theme cycle), Security (add passkey + biometric app-lock),
 * Support (contact + feedback), About & privacy, Account (email + sign out). Self-contained — it
 * hosts its own contact/feedback/about dialogs and the passkey result snackbar via [actionsVm].
 * Mirrors settings_page.dart.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen(
    themeVm: ThemeViewModel,
    lockVm: AppLockViewModel,
    actionsVm: ActionsViewModel,
    email: String,
    onBack: () -> Unit,
    onSignOut: () -> Unit,
) {
    val theme by themeVm.theme.collectAsStateWithLifecycle()
    val lockOn by lockVm.enabled.collectAsStateWithLifecycle()
    val context = LocalContext.current
    val activity = context as? FragmentActivity
    val lockAvailable = activity != null && AppBiometric.available(activity)
    val passkeyAvailable = AppConfig.brokerAvailable
    val scope = rememberCoroutineScope()
    val snackbar = remember { SnackbarHostState() }

    var contactOpen by remember { mutableStateOf(false) }
    var feedbackOpen by remember { mutableStateOf(false) }
    var aboutOpen by remember { mutableStateOf(false) }
    var rulesOpen by remember { mutableStateOf(false) }

    fun toast(msg: String) = scope.launch { snackbar.showSnackbar(msg) }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Settings") },
                navigationIcon = { IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back") } },
            )
        },
        snackbarHost = { SnackbarHost(snackbar) },
    ) { padding ->
        LazyColumn(Modifier.fillMaxWidth().padding(padding)) {
            item { Header("Appearance") }
            item {
                ListItem(
                    leadingContent = { Icon(Icons.Filled.Brightness6, contentDescription = null) },
                    headlineContent = { Text("Theme") },
                    supportingContent = { Text(theme.label) },
                    modifier = Modifier.clickable { themeVm.cycle() },
                )
            }
            item { HorizontalDivider() }

            item { Header("Security") }
            if (passkeyAvailable) {
                item {
                    ListItem(
                        leadingContent = { Icon(Icons.Filled.Key, contentDescription = null) },
                        headlineContent = { Text("Add a passkey") },
                        supportingContent = { Text("Recommended — sign in with your fingerprint, face, or PIN instead of a password") },
                        modifier = Modifier.clickable {
                            actionsVm.addPasskey(context) { _, msg -> toast(msg) }
                        },
                    )
                }
            }
            if (lockAvailable) {
                item {
                    ListItem(
                        leadingContent = { Icon(Icons.Filled.Fingerprint, contentDescription = null) },
                        headlineContent = { Text("App lock") },
                        supportingContent = { Text("Require biometrics to open the app") },
                        trailingContent = {
                            Switch(
                                checked = lockOn,
                                onCheckedChange = { target ->
                                    if (target && activity != null) {
                                        scope.launch { if (AppBiometric.authenticate(activity)) lockVm.set(true) }
                                    } else lockVm.set(false)
                                },
                            )
                        },
                    )
                }
            }
            if (!passkeyAvailable && !lockAvailable) {
                item {
                    ListItem(
                        leadingContent = { Icon(Icons.Outlined.Info, contentDescription = null) },
                        headlineContent = { Text("No extra security options on this device") },
                    )
                }
            }
            item { HorizontalDivider() }

            item { Header("Support") }
            item {
                ListItem(
                    leadingContent = { Icon(Icons.Filled.SupportAgent, contentDescription = null) },
                    headlineContent = { Text("Contact support") },
                    supportingContent = { Text("Message the app owner") },
                    modifier = Modifier.clickable { contactOpen = true },
                )
            }
            item {
                ListItem(
                    leadingContent = { Icon(Icons.Outlined.Feedback, contentDescription = null) },
                    headlineContent = { Text("Send feedback") },
                    supportingContent = { Text("Report a bug or suggest an improvement") },
                    modifier = Modifier.clickable { feedbackOpen = true },
                )
            }
            item { HorizontalDivider() }

            item { Header("About") }
            item {
                ListItem(
                    leadingContent = { Icon(Icons.Outlined.Info, contentDescription = null) },
                    headlineContent = { Text("About & privacy") },
                    modifier = Modifier.clickable { aboutOpen = true },
                )
            }
            item {
                ListItem(
                    leadingContent = { Icon(Icons.Outlined.Info, contentDescription = null) },
                    headlineContent = { Text("Rules & definitions") },
                    supportingContent = { Text("Eligibility, data access & convert-care") },
                    modifier = Modifier.clickable { rulesOpen = true },
                )
            }
            item { HorizontalDivider() }

            item { Header("Account") }
            item {
                ListItem(
                    leadingContent = { Icon(Icons.Filled.AccountCircle, contentDescription = null) },
                    headlineContent = { Text("Signed in as") },
                    supportingContent = { Text(email.ifEmpty { "—" }) },
                )
            }
            item {
                ListItem(
                    leadingContent = { Icon(Icons.AutoMirrored.Filled.Logout, contentDescription = null, tint = MaterialTheme.colorScheme.error) },
                    headlineContent = { Text("Sign out", color = MaterialTheme.colorScheme.error) },
                    modifier = Modifier.clickable(onClick = onSignOut),
                )
            }
            item { Spacer(Modifier.size(24.dp)) }
        }
    }

    if (contactOpen) ContactDialog(onDismiss = { contactOpen = false }) { subj, msg -> actionsVm.contact(subj, msg) { _, r -> toast(r) } }
    if (feedbackOpen) FeedbackDialog(onDismiss = { feedbackOpen = false }) { title, body -> actionsVm.feedback(title, body) { _, r -> toast(r) } }
    if (aboutOpen) AboutDialog(onDismiss = { aboutOpen = false })
    if (rulesOpen) RulesDialog(onDismiss = { rulesOpen = false })
}

@Composable
private fun Header(text: String) {
    Text(
        text.uppercase(),
        style = MaterialTheme.typography.labelSmall,
        color = MaterialTheme.colorScheme.primary,
        fontWeight = FontWeight.Bold,
        modifier = Modifier.padding(start = 16.dp, top = 18.dp, bottom = 6.dp),
    )
}
