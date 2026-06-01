package org.membercovenantpath.viewer.ui.screens.tabs

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.item
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.Groups
import androidx.compose.material.icons.filled.Schedule
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import org.membercovenantpath.viewer.logic.Kpis
import org.membercovenantpath.viewer.logic.KpiEvent
import org.membercovenantpath.viewer.logic.Milestones
import org.membercovenantpath.viewer.model.Member
import org.membercovenantpath.viewer.ui.components.CountBadge
import org.membercovenantpath.viewer.ui.components.PhotoAvatar
import org.membercovenantpath.viewer.util.Dates
import java.time.LocalDate

/**
 * The people behind a metric: distribution **by unit** (every unit in scope, including zeros)
 * expandable to names, or **chronologically** by date (with unit shown). Mirrors `_DrillSheet`.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun KpiDrillSheet(
    title: String,
    events: List<KpiEvent>,
    allUnits: Set<String>,
    bucketLabel: String?,
    onOpen: (Member) -> Unit,
    onDismiss: () -> Unit,
) {
    var byUnit by remember { mutableStateOf(true) }
    ModalBottomSheet(onDismissRequest = onDismiss) {
        // One bounded LazyColumn for the whole sheet (header + toggle as items) so we never nest a
        // lazy list inside a wrap-content column.
        LazyColumn(Modifier.fillMaxWidth().heightIn(max = 560.dp).padding(horizontal = 16.dp)) {
            item {
                Text(
                    title + (bucketLabel?.let { " · $it" } ?: ""),
                    style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold,
                )
                Spacer(Modifier.size(10.dp))
                SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth()) {
                    SegmentedButton(
                        selected = byUnit, onClick = { byUnit = true }, shape = SegmentedButtonDefaults.itemShape(0, 2),
                        icon = { Icon(Icons.Filled.Groups, contentDescription = null, modifier = Modifier.size(18.dp)) },
                    ) { Text("By unit") }
                    SegmentedButton(
                        selected = !byUnit, onClick = { byUnit = false }, shape = SegmentedButtonDefaults.itemShape(1, 2),
                        icon = { Icon(Icons.Filled.Schedule, contentDescription = null, modifier = Modifier.size(18.dp)) },
                    ) { Text("By date") }
                }
                Spacer(Modifier.size(12.dp))
            }
            if (byUnit) byUnitItems(events, allUnits, onOpen, onDismiss)
            else chronoItems(events, onOpen, onDismiss)
            item { Spacer(Modifier.size(16.dp)) }
        }
    }
}

private fun androidx.compose.foundation.lazy.LazyListScope.byUnitItems(
    events: List<KpiEvent>,
    allUnits: Set<String>,
    onOpen: (Member) -> Unit,
    onDismiss: () -> Unit,
) {
    val byUnit = LinkedHashMap<String, LinkedHashMap<String, Member>>()
    allUnits.sorted().forEach { byUnit[it] = LinkedHashMap() }
    for (e in events) {
        val u = e.member.unitName ?: "—"
        val id = e.member.personUuid ?: e.member.name ?: ""
        byUnit.getOrPut(u) { LinkedHashMap() }[id] = e.member
    }
    byUnit.entries.sortedBy { it.key }.forEach { (unit, map) ->
        val members = map.values.sortedBy { it.name ?: "" }
        item {
            Row(Modifier.fillMaxWidth().padding(vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                Text(
                    unit, fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f),
                    color = if (members.isEmpty()) MaterialTheme.colorScheme.onSurfaceVariant else MaterialTheme.colorScheme.onSurface,
                )
                CountBadge(members.size)
            }
            members.forEach { m -> PersonTile(m, onOpen, onDismiss) }
            HorizontalDivider()
        }
    }
}

private fun androidx.compose.foundation.lazy.LazyListScope.chronoItems(
    events: List<KpiEvent>,
    onOpen: (Member) -> Unit,
    onDismiss: () -> Unit,
) {
    val sorted = events.sortedByDescending { it.date }
    if (sorted.isEmpty()) {
        item { Box(Modifier.fillMaxWidth().padding(24.dp), contentAlignment = Alignment.Center) { Text("No one in this view.") } }
        return
    }
    items(sorted) { e ->
        PersonTile(e.member, onOpen, onDismiss, subtitle = "${e.member.unitName ?: "—"} · ${Dates.fullLong(e.date)}")
    }
}

@Composable
private fun PersonTile(m: Member, onOpen: (Member) -> Unit, onDismiss: () -> Unit, subtitle: String? = m.unitName) {
    Row(
        Modifier.fillMaxWidth().clip(androidx.compose.foundation.shape.RoundedCornerShape(8.dp))
            .clickable { onDismiss(); onOpen(m) }.padding(vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        PhotoAvatar(name = m.name ?: "?", photoUrl = m.photoUrl, size = 32.dp)
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Text(m.name ?: "—", fontWeight = FontWeight.Medium)
            if (!subtitle.isNullOrEmpty()) {
                Text(subtitle, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
        Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, contentDescription = null, modifier = Modifier.size(18.dp))
    }
}

/**
 * #5 Golden Hour broken out per category, eligible-only (matches the GH tab). Each row shows % and
 * the eligible members still missing it. Mirrors `_showGoldenHourBreakdown`.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun GoldenHourBreakdownSheet(rows: List<Member>, today: LocalDate, onOpen: (Member) -> Unit, onDismiss: () -> Unit) {
    ModalBottomSheet(onDismissRequest = onDismiss) {
        LazyColumn(Modifier.fillMaxWidth().heightIn(max = 560.dp).padding(horizontal = 16.dp, vertical = 0.dp)) {
            item {
                Text("Golden Hour by category", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
                Text(
                    "Eligible-only — members who don't qualify (age, sex, tenure) are excluded so the % reflects who actually still needs it.",
                    style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(top = 4.dp, bottom = 8.dp),
                )
            }
            Milestones.all.forEach { ms ->
                val eligible = rows.filter { ms.eligible(it, today) }
                if (eligible.isEmpty()) return@forEach
                val missing = eligible.filterNot { ms.complete(it) }.sortedBy { it.name ?: "" }
                val done = eligible.size - missing.size
                val pct = done.toFloat() / eligible.size
                item {
                    Column(Modifier.padding(vertical = 8.dp)) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Icon(ms.icon, contentDescription = null, tint = ms.color, modifier = Modifier.size(18.dp))
                            Spacer(Modifier.width(8.dp))
                            Text(ms.label, fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
                            Text("${(pct * 100).toInt()}%  ·  $done/${eligible.size}", fontWeight = FontWeight.SemiBold)
                        }
                        Spacer(Modifier.size(6.dp))
                        LinearProgressIndicator(progress = { pct }, modifier = Modifier.fillMaxWidth().clip(androidx.compose.foundation.shape.RoundedCornerShape(4.dp)))
                        if (missing.isEmpty()) {
                            Text("Everyone eligible has this.", style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(top = 6.dp))
                        } else {
                            missing.forEach { m -> PersonTile(m, onOpen, onDismiss) }
                        }
                        HorizontalDivider(Modifier.padding(top = 6.dp))
                    }
                }
            }
        }
    }
}

/** #38: the members behind "Lessons with a member present", ranked by count. Mirrors `_showLessonsDrill`. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun LessonsDrillSheet(people: List<Kpis.MemberLessons>, onOpen: (Member) -> Unit, onDismiss: () -> Unit) {
    ModalBottomSheet(onDismissRequest = onDismiss) {
        LazyColumn(Modifier.fillMaxWidth().heightIn(max = 560.dp).padding(horizontal = 16.dp)) {
            item {
                Text("Lessons with a member present", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
                Text("${people.size} ${if (people.size == 1) "person" else "people"} · ranked by count", style = MaterialTheme.typography.bodySmall)
                HorizontalDivider(Modifier.padding(vertical = 8.dp))
            }
            if (people.isEmpty()) {
                item { Box(Modifier.fillMaxWidth().padding(20.dp), contentAlignment = Alignment.Center) { Text("No member-present lessons recorded yet.") } }
            } else {
                items(people) { p ->
                    Row(
                        Modifier.fillMaxWidth().clip(androidx.compose.foundation.shape.RoundedCornerShape(8.dp))
                            .clickable { onDismiss(); onOpen(p.member) }.padding(vertical = 8.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        PhotoAvatar(name = p.member.name ?: "?", photoUrl = p.member.photoUrl, size = 34.dp)
                        Spacer(Modifier.width(12.dp))
                        Column(Modifier.weight(1f)) {
                            Text(p.member.name ?: "—", fontWeight = FontWeight.Medium)
                            Text(p.member.unitName ?: "", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                        CountBadge(p.count)
                    }
                }
            }
            item { Spacer(Modifier.size(16.dp)) }
        }
    }
}
