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
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.item
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.Event
import androidx.compose.material.icons.filled.EventAvailable
import androidx.compose.material.icons.filled.Groups
import androidx.compose.material.icons.filled.VolunteerActivism
import androidx.compose.material.icons.filled.WarningAmber
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import org.membercovenantpath.viewer.logic.DateParse
import org.membercovenantpath.viewer.model.Member
import org.membercovenantpath.viewer.model.Missionary
import org.membercovenantpath.viewer.ui.components.CountBadge
import org.membercovenantpath.viewer.ui.components.MissionaryChip
import org.membercovenantpath.viewer.ui.components.PhotoAvatar
import org.membercovenantpath.viewer.ui.components.SectionCard
import org.membercovenantpath.viewer.ui.screens.EmptyPanel
import org.membercovenantpath.viewer.util.Dates
import java.time.LocalDate
import java.time.temporal.ChronoUnit

private val OverdueOrange = Color(0xFFEF6C00) // orange.shade800

private data class Dated(val m: Member, val date: LocalDate)

/**
 * Prospective baptisms: investigators with a planned `baptism_goal_date`, as a date timeline. A
 * **Combined / Per unit** toggle (#12): combined is one timeline; per-unit splits into cards that
 * also show the assigned full-time **missionaries** strip. Each timeline surfaces an overdue
 * ("date passed") block first, then "Scheduled", grouped by date. Ported from baptisms_view.dart.
 */
@Composable
fun BaptismsScreen(
    members: List<Member>,
    missionariesByUnit: Map<String, List<Missionary>>,
    onOpen: (Member) -> Unit,
    today: LocalDate = LocalDate.now(),
) {
    var byUnit by remember { mutableStateOf(false) }

    val items = members
        .filter { it.isInvestigator }
        .mapNotNull { m -> DateParse.parseMemberDate(m.baptismGoalDate)?.let { Dated(m, it) } }
        .sortedBy { it.date }

    LazyColumn(modifier = Modifier.fillMaxWidth(), contentPadding = PaddingValues(14.dp)) {
        item {
            Row(
                Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    AccentTitle("Prospective Baptisms")
                    Spacer(Modifier.width(8.dp))
                    CountBadge(items.size)
                }
                LayoutToggle(byUnit) { byUnit = it }
            }
            Spacer(Modifier.size(8.dp))
        }

        if (items.isEmpty()) {
            item { EmptyPanel("No prospective baptisms with a planned date.") }
            return@LazyColumn
        }

        if (!byUnit) {
            timeline(items, today, onOpen, embedded = false)
        } else {
            val grouped = items.groupBy { it.m.unitName ?: "—" }.toSortedMap()
            grouped.forEach { (unit, list) ->
                item {
                    SectionCard(title = unit, leadingIcon = Icons.Filled.Groups, trailing = { CountBadge(list.size) }) {
                        Column {
                            val miss = missionariesByUnit[unit].orEmpty()
                            if (miss.isNotEmpty()) {
                                MissionaryStrip(miss)
                                HorizontalDivider(Modifier.padding(vertical = 9.dp))
                            }
                            EmbeddedTimeline(list, today, onOpen)
                        }
                    }
                }
            }
        }
    }
}

/** Combined timeline: overdue card then scheduled card (each its own list item). */
private fun androidx.compose.foundation.lazy.LazyListScope.timeline(
    items: List<Dated>,
    today: LocalDate,
    onOpen: (Member) -> Unit,
    embedded: Boolean,
) {
    val overdue = items.filter { it.date.isBefore(today) }
    val upcoming = items.filterNot { it.date.isBefore(today) }
    if (overdue.isNotEmpty()) {
        item {
            DateSectionCard("Needs attention — date passed", Icons.Filled.WarningAmber, OverdueOrange, overdue, true, today, onOpen)
        }
    }
    if (upcoming.isNotEmpty()) {
        item {
            DateSectionCard("Scheduled", Icons.Filled.EventAvailable, null, upcoming, false, today, onOpen)
        }
    }
}

@Composable
private fun EmbeddedTimeline(items: List<Dated>, today: LocalDate, onOpen: (Member) -> Unit) {
    val overdue = items.filter { it.date.isBefore(today) }
    val upcoming = items.filterNot { it.date.isBefore(today) }
    Column {
        if (overdue.isNotEmpty()) {
            EmbeddedSection("Needs attention — date passed", Icons.Filled.WarningAmber, OverdueOrange, overdue, true, today, onOpen)
        }
        if (upcoming.isNotEmpty()) {
            EmbeddedSection("Scheduled", Icons.Filled.EventAvailable, MaterialTheme.colorScheme.primary, upcoming, false, today, onOpen)
        }
    }
}

@Composable
private fun AccentTitle(title: String) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Box(
            Modifier.padding(end = 10.dp).size(width = 4.dp, height = 22.dp)
                .clip(RoundedCornerShape(2.dp)).background(MaterialTheme.colorScheme.primary),
        )
        Text(title, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
    }
}

@Composable
private fun LayoutToggle(byUnit: Boolean, onChange: (Boolean) -> Unit) {
    SingleChoiceSegmentedButtonRow {
        SegmentedButton(
            selected = !byUnit, onClick = { onChange(false) },
            shape = SegmentedButtonDefaults.itemShape(0, 2),
            icon = { Icon(Icons.Filled.Event, contentDescription = null, modifier = Modifier.size(16.dp)) },
        ) { Text("Date") }
        SegmentedButton(
            selected = byUnit, onClick = { onChange(true) },
            shape = SegmentedButtonDefaults.itemShape(1, 2),
            icon = { Icon(Icons.Filled.Groups, contentDescription = null, modifier = Modifier.size(16.dp)) },
        ) { Text("Unit") }
    }
}

@Composable
private fun DateSectionCard(
    title: String,
    icon: ImageVector,
    color: Color?,
    items: List<Dated>,
    overdue: Boolean,
    today: LocalDate,
    onOpen: (Member) -> Unit,
) {
    val accent = color ?: MaterialTheme.colorScheme.primary
    val byDate = items.groupBy { it.date }.toSortedMap()
    SectionCard(title = title, leadingIcon = icon, iconColor = accent) {
        Column {
            byDate.entries.forEachIndexed { i, (date, people) ->
                if (i > 0) HorizontalDivider(Modifier.padding(vertical = 9.dp), color = MaterialTheme.colorScheme.outlineVariant)
                DateRow(date, people, overdue, today, onOpen)
            }
        }
    }
}

@Composable
private fun EmbeddedSection(
    title: String,
    icon: ImageVector,
    color: Color,
    items: List<Dated>,
    overdue: Boolean,
    today: LocalDate,
    onOpen: (Member) -> Unit,
) {
    val byDate = items.groupBy { it.date }.toSortedMap()
    Column(Modifier.padding(top = 4.dp, bottom = 6.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(icon, contentDescription = null, tint = color, modifier = Modifier.size(16.dp))
            Spacer(Modifier.width(6.dp))
            Text(title, color = color, fontWeight = FontWeight.Bold, fontSize = 13.sp)
        }
        Spacer(Modifier.size(8.dp))
        byDate.entries.forEachIndexed { i, (date, people) ->
            if (i > 0) HorizontalDivider(Modifier.padding(vertical = 9.dp), color = MaterialTheme.colorScheme.outlineVariant)
            DateRow(date, people, overdue, today, onOpen)
        }
    }
}

@Composable
private fun DateRow(date: LocalDate, people: List<Dated>, overdue: Boolean, today: LocalDate, onOpen: (Member) -> Unit) {
    val accent = if (overdue) OverdueOrange else MaterialTheme.colorScheme.primary
    val days = ChronoUnit.DAYS.between(today, date).toInt()
    val rel = when {
        overdue -> "${-days} day${if (days == -1) "" else "s"} ago"
        days == 0 -> "Today"
        days == 1 -> "Tomorrow"
        else -> "in $days days"
    }
    Row(verticalAlignment = Alignment.Top) {
        Column(
            modifier = Modifier.width(54.dp).clip(RoundedCornerShape(10.dp))
                .background(accent.copy(alpha = 0.10f)).padding(vertical = 6.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text(Dates.monthAbbrUpper(date), fontSize = 11.sp, color = accent, fontWeight = FontWeight.Bold)
            Text("${date.dayOfMonth}", fontSize = 22.sp, color = accent, fontWeight = FontWeight.Bold)
            Text(Dates.weekdayAbbr(date), fontSize = 10.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Text(
                rel, fontSize = 11.sp,
                color = if (overdue) accent else MaterialTheme.colorScheme.onSurfaceVariant,
                fontWeight = FontWeight.SemiBold, modifier = Modifier.padding(top = 3.dp, bottom = 1.dp),
            )
            people.forEach { p ->
                Row(
                    modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(8.dp))
                        .clickable { onOpen(p.m) }.padding(vertical = 5.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    PhotoAvatar(name = p.m.name ?: "?", photoUrl = p.m.photoUrl, size = 36.dp)
                    Spacer(Modifier.width(10.dp))
                    Column(Modifier.weight(1f)) {
                        Text(p.m.name ?: "—", fontWeight = FontWeight.SemiBold)
                        Text(p.m.unitName ?: "", fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, contentDescription = null, modifier = Modifier.size(18.dp))
                }
            }
        }
    }
}

/** The full-time missionaries assigned to a unit (#12): name chips → tap shows phone/email. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun MissionaryStrip(missionaries: List<Missionary>) {
    Row(verticalAlignment = Alignment.Top) {
        Icon(Icons.Filled.VolunteerActivism, contentDescription = null, tint = MaterialTheme.colorScheme.primary, modifier = Modifier.size(16.dp))
        Spacer(Modifier.width(6.dp))
        FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            missionaries.forEach { MissionaryChip(it) }
        }
    }
}
