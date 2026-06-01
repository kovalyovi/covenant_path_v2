package org.membercovenantpath.viewer.ui.components

import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.SyncProblem
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.delay
import org.membercovenantpath.viewer.logic.Freshness
import java.time.Instant
import java.time.temporal.ChronoUnit

/**
 * Live "syncing your stake" banner with an elapsed-time counter (#9). [startedAtIso] drives the
 * timer; the parent stops passing it when sync_state flips to done. Mirrors `_SyncingBanner`.
 */
@Composable
fun SyncingBanner(startedAtIso: String?) {
    var nowTick by remember { mutableLongStateOf(0L) }
    LaunchedEffect(startedAtIso) {
        while (true) { delay(1000); nowTick++ }
    }
    val elapsed = remember(nowTick, startedAtIso) {
        val started = Freshness.parseInstant(startedAtIso) ?: return@remember ""
        val d = ChronoUnit.SECONDS.between(started, Instant.now()).coerceAtLeast(0)
        val m = d / 60; val s = d % 60
        if (m > 0) " · ${m}m ${s}s elapsed" else " · ${s}s elapsed"
    }
    Surface(color = MaterialTheme.colorScheme.secondaryContainer, modifier = Modifier.fillMaxWidth()) {
        Row(
            Modifier.padding(horizontal = 16.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            CircularProgressIndicator(
                strokeWidth = 2.dp,
                color = MaterialTheme.colorScheme.onSecondaryContainer,
                modifier = Modifier.size(16.dp),
            )
            Spacer(Modifier.width(12.dp))
            Text(
                "Syncing your stake from LCR — fresh data in a few minutes$elapsed.",
                color = MaterialTheme.colorScheme.onSecondaryContainer,
            )
        }
    }
}

/** Revoked-credential banner: sync paused → re-enroll (#9). Mirrors `_StaleBanner`. */
@Composable
fun StaleCredentialBanner(onReenroll: () -> Unit) {
    Surface(color = MaterialTheme.colorScheme.surfaceVariant, modifier = Modifier.fillMaxWidth()) {
        Row(
            Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(Icons.Filled.SyncProblem, contentDescription = null, tint = Color(0xFFEF6C00))
            Spacer(Modifier.width(10.dp))
            Text(
                "Sync paused — credential revoked. Re-enroll to resume daily updates.",
                modifier = Modifier.weight(1f),
                style = MaterialTheme.typography.bodyMedium,
            )
            TextButton(onClick = onReenroll) { Text("Re-enroll") }
        }
    }
}
