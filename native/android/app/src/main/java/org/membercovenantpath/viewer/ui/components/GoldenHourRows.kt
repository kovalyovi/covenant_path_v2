package org.membercovenantpath.viewer.ui.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.RadioButtonUnchecked
import androidx.compose.material.icons.filled.WarningAmber
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import org.membercovenantpath.viewer.logic.Milestone
import org.membercovenantpath.viewer.logic.Milestones
import org.membercovenantpath.viewer.model.Member
import java.time.LocalDate

/**
 * Golden Hour completion — the user-chosen layout: ONE ROW PER ITEM with a status icon.
 *   ✓ done (green check)   ○ not done (outline circle)   ⚠ data issue (amber warning)
 * N/A items are OMITTED entirely (not eligible — handled upstream in `Milestones.goldenHourRows`), so
 * this view never renders a "N/A" row. The ⚠ row is visibly distinct from both done and not-done.
 *
 * Ported 1:1 from web `components/GoldenHourRows.tsx`. Used by the per-person Baptisms card and the
 * friend/investigator detail to show each Golden Hour step's status at a glance.
 */
private val GREEN = Color(0xFF2E7D32)
private val AMBER = Color(0xFFF9A825)

@Composable
fun GoldenHourRows(
    member: Member,
    list: List<Milestone> = Milestones.all,
    today: LocalDate = LocalDate.now(),
    modifier: Modifier = Modifier,
) {
    val rows = Milestones.goldenHourRows(member, list, today)
    if (rows.isEmpty()) {
        Text(
            "No Golden Hour steps apply yet.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = modifier,
        )
        return
    }
    Column(modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(2.dp)) {
        rows.forEach { GoldenHourRow(it) }
    }
}

@Composable
private fun GoldenHourRow(row: Milestones.GhRow) {
    val (icon, color, label) = when (row.status) {
        Milestones.GhRowStatus.DONE -> Triple(Icons.Filled.CheckCircle, GREEN, "Done")
        Milestones.GhRowStatus.ISSUE -> Triple(Icons.Filled.WarningAmber, AMBER, "Needs data")
        Milestones.GhRowStatus.NOT_DONE ->
            Triple(Icons.Filled.RadioButtonUnchecked, MaterialTheme.colorScheme.onSurfaceVariant, "Not yet")
    }
    Row(
        Modifier.fillMaxWidth().padding(vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(icon, contentDescription = label, tint = color, modifier = Modifier.size(18.dp))
        Spacer(Modifier.width(10.dp))
        Text(
            row.milestone.label,
            style = MaterialTheme.typography.bodyMedium,
            modifier = Modifier.weight(1f),
        )
        Text(label, color = color, style = MaterialTheme.typography.bodySmall, fontWeight = FontWeight.Medium)
    }
}
