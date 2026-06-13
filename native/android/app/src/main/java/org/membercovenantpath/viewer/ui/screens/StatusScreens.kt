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
 * Empty-members state with the right message + action per enrollment status (#11). Mirrors the web
 * `EmptyState`: no-role/no-credential → "Authorize stake sync"; revoked → "sync paused / re-authorize";
 * stale → "needs re-authorization / re-authorize"; active → "setting up your stake…"; otherwise the
 * generic scoped-to-your-calling message. Every action opens the in-app re-auth modal via
 * [onAuthorize] — never bounces the signed-in user back to the login screen.
 */
@Composable
fun EnrollmentEmptyState(
    enrollStatus: org.membercovenantpath.viewer.data.EnrollmentStatus?,
    brokerAvailable: Boolean,
    onAuthorize: () -> Unit,
) {
    val cred = enrollStatus?.credential
    val hasNoRole = enrollStatus?.noRole == true

    // Default (also the enrollStatus == null and unmatched-fallback cases): signed in but no stake/role
    // resolved for this email — it isn't linked yet. Name the TWO ways in (a leader invites them, OR one
    // Church login binds their calling), not the dead-end "sign in with the right email" — they ARE in.
    var title = "No stake linked to this sign-in"
    var body = "You're signed in, but this email isn't linked to a stake yet. Ask your stake leader to " +
        "invite you, or sign in once with your Church account to link your calling automatically."
    var actionLabel: String? = null

    when {
        enrollStatus == null -> {}
        hasNoRole && !enrollStatus?.stakeName.isNullOrBlank() -> {
            // Released-or-no-access member of a KNOWN stake (resolved via the broker's identity
            // cache — ADR-009 amendment G): tell the truth instead of "set up stake sync" /
            // "setting up your stake…" (nothing is coming for them).
            title = "No access with your current calling"
            body = "${enrollStatus?.stakeName} is synced with Covenant Path, but your current calling " +
                "doesn't grant access to its member data. If you were recently released, access ends " +
                "automatically. If this seems wrong, contact your stake leadership."
        }
        hasNoRole && cred?.isNone == true -> {
            // No role AND no stake we can name — this email isn't linked to a stake. We can't tell a
            // brand-new-stake LEADER from an unlinked VIEWER, so present both true paths: a leader signs
            // in with their Church account (sets up sync / binds their calling); a viewer asks to be
            // invited by email.
            if (brokerAvailable) {
                title = "Link your stake access"
                body = "You're signed in, but this email isn't linked to a stake yet. If your stake " +
                    "already uses Covenant Path, ask a stake leader to invite you by email. If you lead " +
                    "the stake, sign in with your Church account to set it up — that also links your calling."
                actionLabel = "Sign in with Church account"
            } else {
                title = "Not linked to a stake yet"
                body = "Ask your stake leader to invite you by email, or to set up Covenant Path with " +
                    "their Church account. Once your email is linked, this code sign-in shows your stake."
            }
        }
        cred?.isRevoked == true -> {
            title = "Sync paused"
            body = "The daily sync credential for your stake has been revoked. Re-authorize to resume data updates."
            if (brokerAvailable) actionLabel = "Re-authorize"
        }
        cred?.isStale == true -> {
            title = "Sync needs re-authorization"
            body = "This stake's daily sync stopped — the Church session that keeps it updated expired. Re-authorize with your Church account to resume updates."
            if (brokerAvailable) actionLabel = "Re-authorize"
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
                Button(onClick = onAuthorize, modifier = Modifier.padding(top = 20.dp)) { Text(actionLabel) }
            }
        }
    }
}
