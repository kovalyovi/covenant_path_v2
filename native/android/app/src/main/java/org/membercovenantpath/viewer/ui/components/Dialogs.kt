package org.membercovenantpath.viewer.ui.components

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

/** Contact-support dialog (#25): subject (optional) + message → broker /contact. */
@Composable
fun ContactDialog(onDismiss: () -> Unit, onSend: (subject: String, message: String) -> Unit) {
    var subject by remember { mutableStateOf("") }
    var message by remember { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Contact support") },
        text = {
            Column {
                Text("Send a message to the app owner. They'll reply to your sign-in email.")
                Spacer(Modifier.size(8.dp))
                OutlinedTextField(subject, { subject = it }, label = { Text("Subject (optional)") }, singleLine = true, modifier = Modifier.fillMaxWidth())
                Spacer(Modifier.size(8.dp))
                OutlinedTextField(message, { message = it }, label = { Text("How can we help?") }, minLines = 3, maxLines = 6, modifier = Modifier.fillMaxWidth())
            }
        },
        confirmButton = { TextButton(onClick = { onSend(subject, message); onDismiss() }, enabled = message.isNotBlank()) { Text("Send") } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}

/** Send-feedback dialog (#25): summary + details → broker /feedback (a GitHub issue). */
@Composable
fun FeedbackDialog(onDismiss: () -> Unit, onSend: (title: String, body: String) -> Unit) {
    var title by remember { mutableStateOf("") }
    var body by remember { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Send feedback") },
        text = {
            Column {
                OutlinedTextField(title, { title = it }, label = { Text("Summary") }, singleLine = true, modifier = Modifier.fillMaxWidth())
                Spacer(Modifier.size(8.dp))
                OutlinedTextField(body, { body = it }, label = { Text("Details (optional)") }, minLines = 3, maxLines = 6, modifier = Modifier.fillMaxWidth())
            }
        },
        confirmButton = { TextButton(onClick = { onSend(title, body); onDismiss() }, enabled = title.isNotBlank()) { Text("Send") } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}

/** "About & privacy" — the full disclaimer + how credentials are handled. Mirrors disclaimer.dart. */
@Composable
fun AboutDialog(onDismiss: () -> Unit) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("About & privacy") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState())) {
                Text(Disclaimer.LONG)
                Spacer(Modifier.size(12.dp))
                Text("Privacy", style = androidx.compose.material3.MaterialTheme.typography.titleSmall)
                Spacer(Modifier.size(4.dp))
                Text(Disclaimer.PRIVACY)
            }
        },
        confirmButton = { TextButton(onClick = onDismiss) { Text("Close") } },
    )
}

/** A simple yes/no confirmation dialog (revoke, sync, etc.). */
@Composable
fun ConfirmDialog(
    title: String,
    message: String,
    confirmLabel: String,
    onConfirm: () -> Unit,
    onDismiss: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title) },
        text = { Text(message) },
        confirmButton = { TextButton(onClick = { onDismiss(); onConfirm() }) { Text(confirmLabel) } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}

/** Disclaimer copy, mirroring disclaimer.dart's constants. */
object Disclaimer {
    const val SHORT = "Independent tool · not affiliated with or endorsed by the Church · built by ILYA Kovalyov."
    const val LONG = "Covenant Path is an independent tool built by ILYA Kovalyov to help leaders track new and " +
        "prospective members' covenant path. It is NOT an official product of The Church of Jesus Christ of " +
        "Latter-day Saints."
    const val PRIVACY = "Sign in with your Church (LCR) account is used to retrieve your stake's data on your behalf. " +
        "Your session is stored encrypted — your password is never stored — access is scoped to your calling, and " +
        "you can revoke it at any time."
}
