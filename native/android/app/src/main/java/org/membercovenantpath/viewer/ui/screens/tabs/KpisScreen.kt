package org.membercovenantpath.viewer.ui.screens.tabs

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.item
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Insights
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import org.membercovenantpath.viewer.logic.Milestones
import org.membercovenantpath.viewer.model.Member
import org.membercovenantpath.viewer.ui.components.BigHeader
import org.membercovenantpath.viewer.ui.components.SectionCard
import org.membercovenantpath.viewer.ui.theme.TabColors

/**
 * KPIs — STUB for the PoC (lowest priority per SPEC.md; the Flutter app draws fl_chart line charts
 * with week/month/year windows + prev-period overlays). We surface a couple of honest summary
 * numbers so the tab isn't blank, and clearly label it as a stub. Wiring real charts (Compose has
 * no first-party chart lib; would add e.g. Vico) is left as the obvious next step.
 */
@Composable
fun KpisScreen(members: List<Member>) {
    val baptized = members.filterNot { it.isInvestigator }
    val investigators = members.filter { it.isInvestigator }
    val avg = Milestones.avgCompletion(baptized)

    LazyColumn(Modifier.fillMaxWidth(), contentPadding = PaddingValues(14.dp)) {
        item {
            BigHeader("KPIs", "Stake metrics (stub)")
            Spacer(Modifier.size(8.dp))
        }
        item {
            SectionCard(title = "Summary", leadingIcon = Icons.Filled.Insights, iconColor = TabColors.Kpis) {
                Column {
                    StatLine("New members", baptized.size.toString())
                    StatLine("Being taught", investigators.size.toString())
                    StatLine("Avg. Golden Hour completion", "${(avg * 100).toInt()}%")
                }
            }
        }
        item {
            SectionCard(title = "Charts") {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Icon(Icons.Filled.Insights, contentDescription = null, tint = MaterialTheme.colorScheme.onSurfaceVariant)
                    Spacer(Modifier.size(10.dp))
                    Text(
                        "Time-series charts (sacrament attendance, lessons, new converts) are not " +
                            "implemented in this proof-of-concept.",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }
    }
}

@Composable
private fun StatLine(label: String, value: String) {
    Row(
        Modifier.fillMaxWidth().padding(vertical = 6.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text(label, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(value, fontWeight = FontWeight.Bold)
    }
}
