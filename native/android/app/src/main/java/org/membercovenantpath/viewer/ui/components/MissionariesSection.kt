package org.membercovenantpath.viewer.ui.components

import android.content.Intent
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.VolunteerActivism
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.core.net.toUri
import androidx.compose.material3.Icon
import org.membercovenantpath.viewer.model.Missionary

/**
 * A compact chip row of a unit's full-time missionaries (tap a chip → phone/email). Mirrors web
 * `Missionaries.MissionaryStrip`. Renders nothing when the list is empty.
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun MissionaryStrip(missionaries: List<Missionary>) {
    if (missionaries.isEmpty()) return
    Row(verticalAlignment = Alignment.Top) {
        Icon(
            Icons.Filled.VolunteerActivism,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.primary,
            modifier = Modifier.size(16.dp),
        )
        Spacer(Modifier.width(6.dp))
        FlowRow(
            horizontalArrangement = Arrangement.spacedBy(6.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            missionaries.forEach { MissionaryChip(it) }
        }
    }
}

/**
 * A detail-style list of a unit's missionaries with tappable contact lines (used in the per-person
 * Baptisms card's "Missionaries by Unit" section and the friend/investigator detail). Renders a clean
 * empty state when none are assigned/synced for the unit. Mirrors web `Missionaries.MissionariesSection`.
 */
@Composable
fun MissionariesSection(unitName: String?, missionaries: List<Missionary>, title: String = "Full-Time Missionaries") {
    SectionCard(title = title, leadingIcon = Icons.Filled.VolunteerActivism) {
        if (missionaries.isEmpty()) {
            Text(
                "No assigned missionaries on record for ${if (!unitName.isNullOrBlank()) "$unitName." else "this unit."}",
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        } else {
            Column {
                missionaries.forEach { MissionaryContactRow(it) }
            }
        }
    }
}

@Composable
private fun MissionaryContactRow(m: Missionary) {
    val context = LocalContext.current
    val phone = m.phone?.takeIf { it.isNotBlank() }
    val email = m.email?.takeIf { it.isNotBlank() }
    Row(Modifier.padding(vertical = 4.dp), verticalAlignment = Alignment.Top) {
        PhotoAvatar(name = m.name ?: "?", photoUrl = m.photoUrl, size = 32.dp)
        Spacer(Modifier.width(10.dp))
        Column {
            Text(m.name ?: "—")
            phone?.let {
                Text(
                    it,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.primary,
                    modifier = Modifier.clickable {
                        runCatching { context.startActivity(Intent(Intent.ACTION_DIAL, "tel:$it".toUri())) }
                    },
                )
            }
            email?.let {
                Text(
                    it,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.primary,
                    modifier = Modifier.clickable {
                        runCatching { context.startActivity(Intent(Intent.ACTION_SENDTO, "mailto:$it".toUri())) }
                    },
                )
            }
        }
    }
}
