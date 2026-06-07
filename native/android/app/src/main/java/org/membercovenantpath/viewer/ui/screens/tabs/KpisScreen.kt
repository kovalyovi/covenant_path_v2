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
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.automirrored.filled.LibraryBooks
import androidx.compose.material.icons.filled.ArrowDropDown
import androidx.compose.material.icons.filled.CompareArrows
import androidx.compose.material.icons.filled.EventAvailable
import androidx.compose.material.icons.filled.Favorite
import androidx.compose.material.icons.filled.Groups
import androidx.compose.material.icons.filled.Leaderboard
import androidx.compose.material3.DatePicker
import androidx.compose.material3.DatePickerDialog
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberDatePickerState
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
import org.membercovenantpath.viewer.logic.BaptismWindow
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
    // #7: custom date range (used when period == CUSTOM). Defaults to Jan 1 → today.
    var customStart by remember { mutableStateOf(LocalDate.of(today.year, 1, 1)) }
    var customEnd by remember { mutableStateOf(today) }
    val customRange = if (period == KpiPeriod.CUSTOM) customStart to customEnd else null

    val units = remember(members) {
        members.mapNotNull { it.unitName?.takeIf { u -> u.isNotEmpty() } }.distinct().sorted()
    }
    val rows = if (unit == null) members else members.filter { it.unitName == unit }
    val baptized = rows.filterNot { it.isInvestigator }
    val investigators = rows.filter { it.isInvestigator }
    val allUnits = rows.map { it.unitName ?: "—" }.toSet()

    val friendsAtSac = Kpis.metricData(investigators, { Kpis.attendedDates(it) }, period, today, customRange)
    val newAtSac = Kpis.metricData(baptized, { Kpis.attendedDates(it) }, period, today, customRange)
    val newFriends = Kpis.metricData(investigators, { Kpis.firstLessonDate(it) }, period, today, customRange)
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
            if (period == KpiPeriod.CUSTOM) {
                Spacer(Modifier.size(8.dp))
                CustomRangeRow(customStart, customEnd, today, onStart = { customStart = it }, onEnd = { customEnd = it })
            }
            Kpis.periodRangeLabel(period, today, customRange)?.let {
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
                ytdTotals = period == KpiPeriod.YTD || period == KpiPeriod.CUSTOM,
                onBucket = { i, lbl -> drill = Drill.Events("Investigators at Sacrament", friendsAtSac.events.filter { it.bucket == i }, lbl) },
                onByUnit = { drill = Drill.Events("Investigators at Sacrament", friendsAtSac.events, null) })
        }
        item {
            MetricChartCard("New Members at Sacrament", Icons.Filled.Favorite, Color(0xFFB5532A),
                newAtSac, allUnits, priorLabel, latestLabel, compare,
                "baptized members who attended sacrament",
                ytdTotals = period == KpiPeriod.YTD || period == KpiPeriod.CUSTOM,
                onBucket = { i, lbl -> drill = Drill.Events("New Members at Sacrament", newAtSac.events.filter { it.bucket == i }, lbl) },
                onByUnit = { drill = Drill.Events("New Members at Sacrament", newAtSac.events, null) })
        }
        item {
            MetricChartCard("New Friends Being Taught", Icons.AutoMirrored.Filled.LibraryBooks, Color(0xFF00897B),
                newFriends, allUnits, priorLabel, latestLabel, compare,
                "people who started lessons in the period",
                ytdTotals = period == KpiPeriod.YTD || period == KpiPeriod.CUSTOM,
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

        // #1: baptisms-by-month chart, folded in from its old "By Month" tab — at the bottom,
        // respecting the unit filter (owns its own YTD/12mo/24mo/All window + by-unit drill).
        item {
            BaptismsCard(baptized, today) { title, events, lbl -> drill = Drill.Events(title, events, lbl) }
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
    val opts = listOf(KpiPeriod.MONTH to "Month", KpiPeriod.YTD to "YTD", KpiPeriod.YEAR to "Year", KpiPeriod.ALL to "All", KpiPeriod.CUSTOM to "Custom")
    SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth()) {
        opts.forEachIndexed { i, (p, lbl) ->
            SegmentedButton(selected = period == p, onClick = { onChange(p) }, shape = SegmentedButtonDefaults.itemShape(i, opts.size)) { Text(lbl) }
        }
    }
}

/** #7: the two date buttons shown when the Custom period is selected; each opens a date picker. */
@Composable
private fun CustomRangeRow(
    start: LocalDate,
    end: LocalDate,
    today: LocalDate,
    onStart: (LocalDate) -> Unit,
    onEnd: (LocalDate) -> Unit,
) {
    val fmt = remember { java.time.format.DateTimeFormatter.ofPattern("MMM d, yyyy") }
    var showStart by remember { mutableStateOf(false) }
    var showEnd by remember { mutableStateOf(false) }
    Row(
        Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.Center,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        OutlinedButton(onClick = { showStart = true }) { Text(fmt.format(start)) }
        Text(" – ", Modifier.padding(horizontal = 6.dp))
        OutlinedButton(onClick = { showEnd = true }) { Text(fmt.format(end)) }
    }
    if (showStart) DateDialog(start, onPick = { onStart(if (it.isAfter(end)) end else it) }) { showStart = false }
    if (showEnd) DateDialog(end, onPick = { onEnd(if (it.isAfter(today)) today else if (it.isBefore(start)) start else it) }) { showEnd = false }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun DateDialog(initial: LocalDate, onPick: (LocalDate) -> Unit, onDismiss: () -> Unit) {
    val state = rememberDatePickerState(
        initialSelectedDateMillis = initial.atStartOfDay(java.time.ZoneOffset.UTC).toInstant().toEpochMilli())
    DatePickerDialog(
        onDismissRequest = onDismiss,
        confirmButton = {
            TextButton(onClick = {
                state.selectedDateMillis?.let {
                    onPick(java.time.Instant.ofEpochMilli(it).atZone(java.time.ZoneOffset.UTC).toLocalDate())
                }
                onDismiss()
            }) { Text("OK") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    ) { DatePicker(state = state) }
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
private fun BaptismsCard(
    baptized: List<Member>,
    today: LocalDate,
    onDrill: (String, List<KpiEvent>, String?) -> Unit,
) {
    var window by remember { mutableStateOf(BaptismWindow.YTD) } // default to year-to-date
    val d = Kpis.baptismsByMonth(baptized, window, today)
    val color = Color(0xFF0277BD)
    SectionCard(title = "Baptisms by month", leadingIcon = Icons.Filled.EventAvailable, iconColor = color) {
        val opts = listOf(
            BaptismWindow.YTD to "YTD", BaptismWindow.M12 to "12 mo",
            BaptismWindow.M24 to "24 mo", BaptismWindow.ALL to "All",
        )
        SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth()) {
            opts.forEachIndexed { i, (w, lbl) ->
                SegmentedButton(
                    selected = window == w,
                    onClick = { window = w },
                    shape = SegmentedButtonDefaults.itemShape(i, opts.size),
                ) { Text(lbl) }
            }
        }
        Spacer(Modifier.size(14.dp))
        Row(Modifier.fillMaxWidth()) {
            BaptismStat("Baptized in window", "${d.total}", Modifier.weight(1f))
            BaptismStat("Best month", d.bestLabel?.let { "$it · ${d.bestCount}" } ?: "—", Modifier.weight(1f))
        }
        Spacer(Modifier.size(14.dp))
        LineChart(
            values = d.counts, labels = d.labels, color = color,
            modifier = Modifier.fillMaxWidth().height(170.dp),
            onBucketTap = { i -> onDrill("Baptisms", d.events.filter { it.bucket == i }, d.labels.getOrNull(i)) },
        )
        Spacer(Modifier.size(8.dp))
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Text(
                "Baptized & confirmed converts, counted by baptism month.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.weight(1f),
            )
            TextButton(onClick = { onDrill("Baptisms", d.events, null) }) {
                Icon(Icons.Filled.Groups, contentDescription = null, modifier = Modifier.size(16.dp))
                Spacer(Modifier.size(4.dp))
                Text("By unit")
            }
        }
    }
}

@Composable
private fun BaptismStat(label: String, value: String, modifier: Modifier = Modifier) {
    Column(modifier) {
        Text(label, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Spacer(Modifier.size(2.dp))
        Text(value, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
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
    ytdTotals: Boolean = false,
    onBucket: (Int, String?) -> Unit,
    onByUnit: () -> Unit,
) {
    val values = metric.series.current
    // #6: for YTD the big-stat pair is YTD TOTALS (this year vs the same Jan–today span last year);
    // otherwise the last two buckets (month-over-month).
    val last: Double?
    val prior: Double?
    if (ytdTotals) {
        last = values.sum()
        prior = metric.series.prev.sum()
    } else {
        last = values.lastOrNull()
        prior = if (values.size >= 2) values[values.size - 2] else null
    }
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
            Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, contentDescription = null, modifier = Modifier.size(18.dp), tint = MaterialTheme.colorScheme.onSurfaceVariant)
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
