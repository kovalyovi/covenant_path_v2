package org.membercovenantpath.viewer.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.item
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Email
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import org.membercovenantpath.viewer.data.arr
import org.membercovenantpath.viewer.data.int
import org.membercovenantpath.viewer.data.str

/**
 * Ad-hoc leader report (#22): stake name + totals (N new · on track · need attention), the
 * most-needed steps, and the outstanding-by-member list, with an "Email to me" action. The shape
 * matches broker GET /report (by_milestone: [[label,count]], outstanding: [{name,unit,missing}]).
 * Mirrors `_ReportSheet`.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ReportSheet(report: JsonObject, onEmail: () -> Unit, onDismiss: () -> Unit) {
    val total = report.int("total")
    val onTrack = report.int("on_track")
    val outstanding = report.arr("outstanding") ?: JsonArray(emptyList())
    val byMilestone = report.arr("by_milestone") ?: JsonArray(emptyList())

    ModalBottomSheet(onDismissRequest = onDismiss) {
        LazyColumn(Modifier.fillMaxWidth().heightIn(max = 560.dp).padding(horizontal = 20.dp)) {
            item {
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    Text(report.str("stake_name") ?: "Convert report", style = MaterialTheme.typography.titleLarge, modifier = Modifier.weight(1f))
                    FilledTonalButton(onClick = { onEmail(); onDismiss() }) {
                        Icon(Icons.Filled.Email, contentDescription = null, modifier = Modifier.size(18.dp))
                        Text("  Email to me")
                    }
                }
                Spacer(Modifier.size(4.dp))
                Text("$total new members · $onTrack on track · ${outstanding.size} need attention", style = MaterialTheme.typography.bodyMedium)
                HorizontalDivider(Modifier.padding(vertical = 12.dp))
            }

            if (byMilestone.isNotEmpty()) {
                item { Text("Most-needed steps", style = MaterialTheme.typography.titleSmall) }
                items(byMilestone.size) { i ->
                    val kv = byMilestone[i] as? JsonArray ?: return@items
                    val label = (kv.getOrNull(0)?.let { stripQuotes(it.toString()) }) ?: ""
                    val count = (kv.getOrNull(1)?.toString()?.trim('"')) ?: ""
                    Row(Modifier.fillMaxWidth().padding(vertical = 2.dp), horizontalArrangement = Arrangement.SpaceBetween) {
                        Text(label, modifier = Modifier.weight(1f))
                        Text(count, fontWeight = FontWeight.SemiBold)
                    }
                }
                item { HorizontalDivider(Modifier.padding(vertical = 12.dp)) }
            }

            if (outstanding.isEmpty()) {
                item {
                    Box(Modifier.fillMaxWidth().padding(20.dp), contentAlignment = Alignment.Center) {
                        Text("Everyone in scope is on track.")
                    }
                }
            } else {
                item { Text("Outstanding by member", style = MaterialTheme.typography.titleSmall) }
                items(outstanding.size) { i ->
                    val o = outstanding[i] as? JsonObject ?: return@items
                    val unit = o.str("unit")
                    val missing = o.arr("missing")?.joinToString(", ") { stripQuotes(it.toString()) } ?: ""
                    Column(Modifier.padding(vertical = 4.dp)) {
                        Text((o.str("name") ?: "—") + (unit?.let { " · $it" } ?: ""), fontWeight = FontWeight.SemiBold)
                        Text(missing, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
            }
        }
    }
}

private fun stripQuotes(s: String) = s.trim().removeSurrounding("\"")

// LazyColumn `items(count)` helper alias kept local to avoid an import clash with other files.
private fun androidx.compose.foundation.lazy.LazyListScope.items(count: Int, block: @Composable (Int) -> Unit) {
    item { Column { repeat(count) { block(it) } } }
}
