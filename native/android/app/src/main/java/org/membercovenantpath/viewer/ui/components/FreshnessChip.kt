package org.membercovenantpath.viewer.ui.components

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.History
import androidx.compose.material.icons.filled.HistoryToggleOff
import androidx.compose.material.icons.filled.Sync
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import org.membercovenantpath.viewer.logic.Freshness

/**
 * App-bar data-freshness chip (#7). "Updated 2h ago" (amber after 2d, red after 2w; icon-only when
 * [compact]); a spinner + "Syncing…" while a scrape runs. Tapping opens a dialog with the exact local
 * time and — when [onSyncNow] is provided (a provider) — a "Sync now" button. Mirrors `_LastUpdated`.
 */
@Composable
fun FreshnessChip(
    iso: String,
    compact: Boolean,
    syncing: Boolean,
    onSyncNow: (() -> Unit)?,
) {
    var open by remember { mutableStateOf(false) }
    val stale = Freshness.staleColor(iso)
    val tint = stale ?: MaterialTheme.colorScheme.onSurfaceVariant

    Row(
        modifier = Modifier
            .clip(RoundedCornerShape(20.dp))
            .clickable { open = true }
            .padding(horizontal = 10.dp, vertical = 6.dp),
        verticalAlignment = androidx.compose.ui.Alignment.CenterVertically,
    ) {
        if (syncing) {
            CircularProgressIndicator(strokeWidth = 2.dp, modifier = Modifier.size(15.dp))
        } else {
            Icon(
                if (stale == null) Icons.Filled.History else Icons.Filled.HistoryToggleOff,
                contentDescription = "Data freshness",
                tint = tint,
                modifier = Modifier.size(18.dp),
            )
        }
        if (!compact) {
            Spacer(Modifier.width(5.dp))
            Text(if (syncing) "Syncing…" else "Updated ${Freshness.ago(iso)}", fontSize = 12.sp, color = tint)
        }
    }

    if (open) {
        AlertDialog(
            onDismissRequest = { open = false },
            title = { Text("Data freshness") },
            text = {
                androidx.compose.foundation.layout.Column {
                    Text("Last scraped from LCR:\n\n${Freshness.exactLocal(iso)}")
                    if (syncing) {
                        Spacer(Modifier.size(14.dp))
                        Row(verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
                            CircularProgressIndicator(strokeWidth = 2.dp, modifier = Modifier.size(16.dp))
                            Spacer(Modifier.width(10.dp))
                            Text(
                                "Sync in progress — fresh data in a few minutes.",
                                style = MaterialTheme.typography.bodySmall,
                            )
                        }
                    } else if (onSyncNow != null) {
                        Spacer(Modifier.size(12.dp))
                        Text(
                            "Run a fresh scrape now using your stake's saved sync credential.",
                            style = MaterialTheme.typography.bodySmall,
                        )
                    }
                }
            },
            confirmButton = {
                if (onSyncNow != null && !syncing) {
                    FilledTonalButton(onClick = { open = false; onSyncNow() }) {
                        Icon(Icons.Filled.Sync, contentDescription = null, modifier = Modifier.size(18.dp))
                        Text("  Sync now")
                    }
                } else {
                    TextButton(onClick = { open = false }) { Text("Close") }
                }
            },
            dismissButton = {
                if (onSyncNow != null && !syncing) {
                    TextButton(onClick = { open = false }) { Text("Close") }
                }
            },
        )
    }
}
