package org.membercovenantpath.viewer.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Groups
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp

@Composable
fun CenteredLoading() {
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        CircularProgressIndicator()
    }
}

@Composable
fun CenteredError(message: String, onRetry: () -> Unit) {
    Box(Modifier.fillMaxSize().padding(24.dp), contentAlignment = Alignment.Center) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Text("Could not load data", style = MaterialTheme.typography.titleMedium)
            Text(
                message,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                textAlign = TextAlign.Center,
                modifier = Modifier.padding(top = 8.dp),
            )
            Button(onClick = onRetry, modifier = Modifier.padding(top = 16.dp)) { Text("Retry") }
        }
    }
}

@Composable
fun EmptyMembers() {
    Box(Modifier.fillMaxSize().padding(32.dp), contentAlignment = Alignment.Center) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center,
        ) {
            Icon(
                Icons.Outlined.Groups,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.primary.copy(alpha = 0.4f),
                modifier = Modifier.size(56.dp),
            )
            Text(
                "No members visible",
                style = MaterialTheme.typography.titleMedium,
                modifier = Modifier.padding(top = 16.dp),
            )
            Text(
                "Access is scoped to your calling. Sign in with the email your stake has on file.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                textAlign = TextAlign.Center,
                modifier = Modifier.padding(top = 8.dp),
            )
        }
    }
}

/** A simple centered "nothing here" panel for an empty tab section. */
@Composable
fun EmptyPanel(text: String) {
    Box(Modifier.fillMaxSize().padding(32.dp), contentAlignment = Alignment.Center) {
        Text(text, textAlign = TextAlign.Center, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

/**
 * Empty-members state with the right message + action per enrollment status (#11). Mirrors the
 * Flutter `_EmptyState`: no-role/no-credential → "set up sync"; revoked → "sync paused / re-enroll";
 * active → "setting up your stake…"; otherwise the generic scoped-to-your-calling message.
 */
@Composable
fun EnrollmentEmptyState(
    enrollStatus: org.membercovenantpath.viewer.data.EnrollmentStatus?,
    brokerAvailable: Boolean,
    onSignOut: () -> Unit,
) {
    val cred = enrollStatus?.credential
    val hasNoRole = enrollStatus?.noRole == true

    var title = "No members visible"
    var body = "Access is scoped to your LCR calling. Sign in with the email your stake has on file."
    var actionLabel: String? = null

    when {
        enrollStatus == null -> {}
        hasNoRole && cred?.isNone == true -> {
            if (brokerAvailable) {
                title = "Set up stake sync"
                body = "Your stake hasn't set up Covenant Path yet. Sign in with your Church account to start daily data updates — signing in keeps your stake synced automatically."
                actionLabel = "Sign in to enable sync"
            } else {
                title = "Stake not set up"
                body = "Ask your stake leader to enable Covenant Path by signing in with their Church account. Once set up, sign in with your email code for access."
            }
        }
        cred?.isRevoked == true -> {
            title = "Sync paused"
            body = "The daily sync credential for your stake has been revoked. Re-enroll to resume data updates."
            if (brokerAvailable) actionLabel = "Re-enroll"
        }
        cred?.isActive == true -> {
            title = "Setting up your stake…"
            body = "Your credential is saved and the first sync is running — your stake's data will appear here in a few minutes. Pull down to refresh. (It also refreshes daily.)"
        }
    }

    Box(Modifier.fillMaxSize().padding(32.dp), contentAlignment = Alignment.Center) {
        Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center) {
            Icon(
                Icons.Outlined.Groups,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.primary.copy(alpha = 0.4f),
                modifier = Modifier.size(56.dp),
            )
            Text(title, style = MaterialTheme.typography.titleMedium, modifier = Modifier.padding(top = 16.dp))
            Text(
                body,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                textAlign = TextAlign.Center,
                modifier = Modifier.padding(top = 8.dp),
            )
            if (actionLabel != null) {
                Button(onClick = onSignOut, modifier = Modifier.padding(top = 20.dp)) { Text(actionLabel) }
            }
        }
    }
}
