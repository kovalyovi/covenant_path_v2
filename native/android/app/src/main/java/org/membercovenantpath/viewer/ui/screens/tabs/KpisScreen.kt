package org.membercovenantpath.viewer.ui.screens.tabs

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.item
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.LibraryBooks
import androidx.compose.material.icons.filled.ArrowDropDown
import androidx.compose.material.icons.filled.CompareArrows
import androidx.compose.material.icons.filled.Favorite
import androidx.compose.material.icons.filled.Groups
import androidx.compose.material.icons.filled.Leaderboard
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import org.membercovenantpath.viewer.logic.DateParse
import org.membercovenantpath.viewer.logic.KpiEvent
import org.membercovenantpath.viewer.logic.KpiMetric
import org.membercovenantpath.viewer.logic.KpiPeriod
import org.membercovenantpath.viewer.logic.Kpis
import org.membercovenantpath.viewer.logic.Milestones
import org.membercovenantpath.viewer.model.Member
import org.membercovenantpath.viewer.ui.components.BigHeader
import org.membercovenantpath.viewer.ui.components.LineChart
import org.membercovenantpath.viewer.ui.components.SectionCard
import java.time.LocalDate
import kotlin.math.roundToInt

/**
 * KPIs from this stake's covenant-path data (#15): metric line-chart cards (Investigators / New
 * Members at Sacrament, New Friends being taught) with a Month/Year/All period, a date-range pill, a
 * Compare-to-previous overlay, a per-unit drill, plus an Overview stat grid and a Golden-Hour-by-unit
 * ranked-bar card. The series/bucketing math is [Kpis] (ported from dashboard_common.dart).
 */
private sealed interface Drill {
    data class Events(val title: String, val events: List<KpiEvent>, val bucketLabel: String?) : Drill
    data class GoldenHour(val rows: List<Member>) : Drill
    data class Lessons(val people: List<Kpis.MemberLessons>) : Drill
}

@Composable
fun KpisScreen(members: List<Member>, onOpen: (Member) -> Unit, today: LocalDate = LocalDate.now()) {
    var period by remember { mutableStateOf(KpiPeriod.MONTH) }
    var unit by remember { mutableStateOf<String?>(null) }
    var compare by remember { mutableStateOf(false) }
    var drill by remember { mutableStateOf<Drill?>(null) }

    val units = remember(members) {
        members.mapNotNull { it.unitName?.takeIf { u -> u.isNotEmpty() } }.distinct().sorted()
    }
    val rows = if (unit == null) members else members.filter { it.unitName == unit }
    val baptized = rows.filterNot { it.isInvestigator }
    val investigators = rows.filter { it.isInvestigator }
    val allUnits = rows.map { it.unitName ?: "—" }.toSet()

    val friendsAtSac = Kpis.metricData(investigators, { Kpis.attendedDates(it) }, period, today)
    val newAtSac = Kpis.metricData(baptized, { Kpis.attendedDates(it) }, period, today)
    val newFriends = Kpis.metricData(investigators, { Kpis.firstLessonDate(it) }, period, today)
    val lessonsWithMember = Kpis.lessonsWithMember(rows)
    val completion = Milestones.avgCompletion(baptized, today)
    val (priorLabel, latestLabel) = Kpis.compareLabels(period)

    fun evs(ms: List<Member>, dateField: (Member) -> String?): List<KpiEvent> =
        ms.map { KpiEvent(it, DateParse.parseMemberDate(dateField(it)) ?: today, 0) }

    LazyColumn(Modifier.fillMaxWidth(), contentPadding = PaddingValues(14.dp)) {
        item {
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.weight(1f)) { BigHeader("KPIs", "From this stake's covenant-path data") }
                if (units.size > 1) UnitDropdown(unit, units) { unit = it }
            }
            Spacer(Modifier.size(10.dp))
            PeriodSelector(period) { period = it }
            Kpis.periodRangeLabel(period, today)?.let {
                Spacer(Modifier.size(6.dp))
                Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) { RangePill(it) }
            }
            if (period != KpiPeriod.ALL) {
                Spacer(Modifier.size(8.dp))
                Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
                    FilterChip(
                        selected = compare,
                        onClick = { compare = !compare },
                        label = { Text("Compare to previous") },
                        leadingIcon = { Icon(Icons.Filled.CompareArrows, contentDescription = null, modifier = Modifier.size(18.dp)) },
                    )
                }
            }
            Spacer(Modifier.size(6.dp))
        }

        item {
            MetricChartCard("Investigators at Sacrament", Icons.Filled.Groups, Color(0xFFEF6C00),
                friendsAtSac, allUnits, priorLabel, latestLabel, compare,
                "people being taught who attended sacrament",
                onBucket = { i, lbl -> drill = Drill.Events("Investigators at Sacrament", friendsAtSac.events.filter { it.bucket == i }, lbl) },
                onByUnit = { drill = Drill.Events("Investigators at Sacrament", friendsAtSac.events, null) })
        }
        item {
            MetricChartCard("New Members at Sacrament", Icons.Filled.Favorite, Color(0xFFB5532A),
                newAtSac, allUnits, priorLabel, latestLabel, compare,
                "baptized members who attended sacrament",
                onBucket = { i, lbl -> drill = Drill.Events("New Members at Sacrament", newAtSac.events.filter { it.bucket == i }, lbl) },
                onByUnit = { drill = Drill.Events("New Members at Sacrament", newAtSac.events, null) })
        }
        item {
            MetricChartCard("New Friends Being Taught", Icons.AutoMirrored.Filled.LibraryBooks, Color(0xFF00897B),
                newFriends, allUnits, priorLabel, latestLabel, compare,
                "people who started lessons in the period",
                onBucket = { i, lbl -> drill = Drill.Events("New Friends Being Taught", newFriends.events.filter { it.bucket == i }, lbl) },
                onByUnit = { drill = Drill.Events("New Friends Being Taught", newFriends.events, null) })
        }

        item {
            OverviewCard(
                beingTaught = investigators.size,
                lessonsWithMember = lessonsWithMember,
                newMembers = baptized.size,
                goldenPct = (completion * 100).roundToInt(),
                onBeingTaught = { drill = Drill.Events("Being taught now", evs(investigators) { it.baptismGoalDate }, null) },
                onLessons = { drill = Drill.Lessons(Kpis.membersWithMemberLessons(rows)) },
                onNewMembers = { drill = Drill.Events("New members tracked", evs(baptized) { it.baptismDate }, null) },
                onGolden = { drill = Drill.GoldenHour(baptized) },
            )
        }

        if (unit == null && units.size > 1) {
            item { UnitCompletionCard(Kpis.unitCompletion(baptized, today)) { unit = it } }
        }
    }

    when (val d = drill) {
        is Drill.Events -> KpiDrillSheet(d.title, d.events, allUnits, d.bucketLabel, onOpen) { drill = null }
        is Drill.GoldenHour -> GoldenHourBreakdownSheet(d.rows, today, onOpen) { drill = null }
        is Drill.Lessons -> LessonsDrillSheet(d.people, onOpen) { drill = null }
        null -> {}
    }
}

@Composable
private fun PeriodSelector(period: KpiPeriod, onChange: (KpiPeriod) -> Unit) {
    val opts = listOf(KpiPeriod.MONTH to "Month", KpiPeriod.YEAR to "Year", KpiPeriod.ALL to "All")
    SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth()) {
        opts.forEachIndexed { i, (p, lbl) ->
            SegmentedButton(selected = period == p, onClick = { onChange(p) }, shape = SegmentedButtonDefaults.itemShape(i, opts.size)) { Text(lbl) }
        }
    }
}

@Composable
private fun UnitDropdown(unit: String?, units: List<String>, onSelect: (String?) -> Unit) {
    var open by remember { mutableStateOf(false) }
    TextButton(onClick = { open = true }) {
        Text(unit ?: "All units", maxLines = 1, overflow = TextOverflow.Ellipsis)
        Icon(Icons.Filled.ArrowDropDown, contentDescription = "Filter unit")
    }
    DropdownMenu(expanded = open, onDismissRequest = { open = false }) {
        DropdownMenuItem(text = { Text("All units") }, onClick = { open = false; onSelect(null) })
        units.forEach { u -> DropdownMenuItem(text = { Text(u) }, onClick = { open = false; onSelect(u) }) }
    }
}

@Composable
private fun RangePill(text: String) {
    Surface(color = MaterialTheme.colorScheme.surfaceVariant, shape = RoundedCornerShape(20.dp)) {
        Text(text, fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(horizontal = 12.dp, vertical = 5.dp))
    }
}

@Composable
private fun MetricChartCard(
    title: String,
    icon: ImageVector,
    color: Color,
    metric: KpiMetric,
    allUnits: Set<String>,
    priorLabel: String,
    latestLabel: String,
    compare: Boolean,
    suffix: String,
    onBucket: (Int, String?) -> Unit,
    onByUnit: () -> Unit,
) {
    val values = metric.series.current
    val last = values.lastOrNull()
    val prior = if (values.size >= 2) values[values.size - 2] else null
    val delta = if (last != null && prior != null) last - prior else null

    SectionCard(
        title = title,
        leadingIcon = icon,
        iconColor = color,
        trailing = delta?.let { d -> @Composable { DeltaBadge(d) } },
        onClick = if (metric.events.isEmpty()) null else onByUnit,
    ) {
        Column {
            if (last != null && prior != null) {
                Row(Modifier.fillMaxWidth()) {
                    BigStat(priorLabel, prior, Modifier.weight(1f))
                    Box(Modifier.width(1.dp).height(46.dp).background(MaterialTheme.colorScheme.outlineVariant).padding(horizontal = 0.dp))
                    BigStat(latestLabel, last, Modifier.weight(1f).padding(start = 14.dp))
                }
                Spacer(Modifier.size(16.dp))
            }
            LineChart(
                values = values,
                labels = metric.series.labels,
                color = color,
                prev = if (compare) metric.series.prev else emptyList(),
                onBucketTap = { i -> onBucket(i, metric.series.labels.getOrNull(i)) },
            )
            Spacer(Modifier.size(8.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(suffix, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.weight(1f))
                TextButton(onClick = onByUnit) {
                    Icon(Icons.Filled.Groups, contentDescription = null, modifier = Modifier.size(16.dp))
                    Text(" By unit")
                }
            }
        }
    }
}

@Composable
private fun BigStat(label: String, v: Double, modifier: Modifier = Modifier) {
    Column(modifier) {
        Text(label, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(
            if (v == v.roundToInt().toDouble()) "${v.roundToInt()}" else "%.1f".format(v),
            style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.Bold,
        )
    }
}

@Composable
private fun DeltaBadge(delta: Double) {
    val up = delta >= 0
    val c = if (up) Color(0xFF2E7D32) else Color(0xFFC62828)
    val v = if (delta == delta.roundToInt().toDouble()) kotlin.math.abs(delta.roundToInt()).toString() else "%.1f".format(kotlin.math.abs(delta))
    Surface(color = c.copy(alpha = 0.12f), shape = RoundedCornerShape(20.dp)) {
        Text("${if (up) "+" else "−"}$v", color = c, fontWeight = FontWeight.SemiBold, fontSize = 12.sp, modifier = Modifier.padding(horizontal = 8.dp, vertical = 3.dp))
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun OverviewCard(
    beingTaught: Int,
    lessonsWithMember: Int,
    newMembers: Int,
    goldenPct: Int,
    onBeingTaught: () -> Unit,
    onLessons: () -> Unit,
    onNewMembers: () -> Unit,
    onGolden: () -> Unit,
) {
    SectionCard(title = "Overview") {
        FlowRow(horizontalArrangement = Arrangement.spacedBy(24.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
            StatTile("$beingTaught", "Being taught now", onBeingTaught)
            StatTile("$lessonsWithMember", "Lessons w/ member present", onLessons)
            StatTile("$newMembers", "New members tracked", onNewMembers)
            StatTile("$goldenPct%", "Golden Hour", onGolden)
        }
    }
}

@Composable
private fun StatTile(value: String, label: String, onClick: () -> Unit) {
    Column(Modifier.width(124.dp).clip(RoundedCornerShape(8.dp)).clickable(onClick = onClick)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(value, style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
            Icon(androidx.compose.material.icons.Icons.AutoMirrored.Filled.KeyboardArrowRight, contentDescription = null, modifier = Modifier.size(18.dp), tint = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        Text(label, style = MaterialTheme.typography.bodySmall)
    }
}

@Composable
private fun UnitCompletionCard(ranked: List<Kpis.UnitPct>, onSelect: (String) -> Unit) {
    if (ranked.size < 2) return
    SectionCard(title = "Golden Hour by unit", leadingIcon = Icons.Filled.Leaderboard) {
        Column {
            ranked.forEach { r ->
                Row(
                    Modifier.fillMaxWidth().clip(RoundedCornerShape(8.dp)).clickable { onSelect(r.unit) }.padding(vertical = 6.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(r.unit, modifier = Modifier.weight(4f), maxLines = 1, overflow = TextOverflow.Ellipsis)
                    Spacer(Modifier.width(8.dp))
                    LinearProgressIndicator(progress = { r.pct.toFloat() }, modifier = Modifier.weight(5f).height(8.dp).clip(RoundedCornerShape(4.dp)))
                    Spacer(Modifier.width(8.dp))
                    Text("${(r.pct * 100).roundToInt()}% · ${r.n}", style = MaterialTheme.typography.bodySmall, modifier = Modifier.width(64.dp))
                }
            }
        }
    }
}
