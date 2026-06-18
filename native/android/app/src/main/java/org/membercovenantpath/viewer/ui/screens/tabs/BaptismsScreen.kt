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
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Event
import androidx.compose.material.icons.filled.EventAvailable
import androidx.compose.material.icons.filled.Groups
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
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import org.membercovenantpath.viewer.logic.DateParse
import org.membercovenantpath.viewer.logic.Milestones
import org.membercovenantpath.viewer.model.Member
import org.membercovenantpath.viewer.model.Missionary
import org.membercovenantpath.viewer.ui.components.CountBadge
import org.membercovenantpath.viewer.ui.components.GoldenHourChips
import org.membercovenantpath.viewer.ui.components.LocalMemberNotes
import org.membercovenantpath.viewer.ui.components.MissionariesSection
import org.membercovenantpath.viewer.ui.components.MissionaryStrip
import org.membercovenantpath.viewer.ui.components.NoteLine
import org.membercovenantpath.viewer.ui.components.PhotoAvatar
import org.membercovenantpath.viewer.ui.components.SectionCard
import org.membercovenantpath.viewer.ui.screens.EmptyPanel
import org.membercovenantpath.viewer.util.Dates
import java.time.LocalDate
import java.time.temporal.ChronoUnit

private val OverdueOrange = Color(0xFFEF6C00) // orange.shade800

private data class Dated(val m: Member, val date: LocalDate)

/**
 * Baptisms tab — a CARD PER PERSON (mirrors web `pages/tabs/BaptismsTab.tsx`). Each investigator with a
 * planned `baptism_goal_date` gets their OWN card: the planned date + countdown, unit, full leader
 * notes, Golden Hour chips + next steps, and the assigned full-time missionaries for their unit.
 * Overdue ("date passed") cards surface first, then "Scheduled". A SECOND section below lists every
 * unit's missionaries ("Missionaries by Unit"). A Unit/Date toggle groups the cards per unit.
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

    // Every stake unit that has missionaries synced — the full per-unit breakdown for the section
    // below (independent of who's in the baptism list, so it's a complete missionary roster).
    val unitsWithMissionaries = missionariesByUnit
        .filter { (u, list) -> u.isNotBlank() && list.isNotEmpty() }
        .keys.sorted()

    LazyColumn(modifier = Modifier.fillMaxWidth(), contentPadding = PaddingValues(14.dp)) {
        item {
            Row(
                Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    AccentTitle("Upcoming Baptisms")
                    Spacer(Modifier.width(8.dp))
                    CountBadge(items.size)
                }
                LayoutToggle(byUnit) { byUnit = it }
            }
            Spacer(Modifier.size(8.dp))
        }

        if (items.isEmpty()) {
            item { EmptyPanel("No baptisms scheduled yet.") }
        } else if (!byUnit) {
            personCardSections(items, today, missionariesByUnit, onOpen)
        } else {
            perUnit(items, today, missionariesByUnit, onOpen)
        }

        // SECOND section: assigned/full-time missionaries — a full per-unit breakdown.
        if (unitsWithMissionaries.isNotEmpty()) {
            item {
                Spacer(Modifier.size(20.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    AccentTitle("Missionaries by Unit")
                    Spacer(Modifier.width(8.dp))
                    CountBadge(unitsWithMissionaries.size)
                }
                Spacer(Modifier.size(4.dp))
            }
            unitsWithMissionaries.forEach { unit ->
                item(key = "miss-$unit") {
                    MissionariesSection(unitName = unit, missionaries = missionariesByUnit[unit].orEmpty(), title = unit)
                }
            }
        }
    }
}

/** People-cards split into "needs attention — date passed" then "scheduled". */
private fun LazyListScope.personCardSections(
    items: List<Dated>,
    today: LocalDate,
    missionariesByUnit: Map<String, List<Missionary>>,
    onOpen: (Member) -> Unit,
) {
    val overdue = items.filter { it.date.isBefore(today) }
    val upcoming = items.filterNot { it.date.isBefore(today) }
    if (overdue.isNotEmpty()) {
        item { GroupHeader("Needs attention — date has passed", Icons.Filled.WarningAmber, OverdueOrange, overdue.size) }
        personCards(overdue, "overdue", today, missionariesByUnit, onOpen, overdue = true)
    }
    if (upcoming.isNotEmpty()) {
        item { GroupHeader("Scheduled", Icons.Filled.EventAvailable, null, upcoming.size) }
        personCards(upcoming, "scheduled", today, missionariesByUnit, onOpen, overdue = false)
    }
}

private fun LazyListScope.personCards(
    list: List<Dated>,
    keyPrefix: String,
    today: LocalDate,
    missionariesByUnit: Map<String, List<Missionary>>,
    onOpen: (Member) -> Unit,
    overdue: Boolean,
) {
    list.forEach { it ->
        item(key = "$keyPrefix-${it.m.personUuid ?: it.m.name}") {
            BaptismPersonCard(it, today, overdue, missionariesByUnit, onOpen)
        }
    }
}

/** The by-unit toggle: one card per unit holding that unit's missionary strip + people-cards. */
private fun LazyListScope.perUnit(
    items: List<Dated>,
    today: LocalDate,
    missionariesByUnit: Map<String, List<Missionary>>,
    onOpen: (Member) -> Unit,
) {
    val grouped = items.groupBy { it.m.unitName ?: "—" }.toSortedMap()
    grouped.forEach { (unit, list) ->
        item(key = "unit-$unit") {
            SectionCard(title = unit, leadingIcon = Icons.Filled.Groups, trailing = { CountBadge(list.size) }) {
                Column {
                    val miss = missionariesByUnit[unit].orEmpty()
                    if (miss.isNotEmpty()) {
                        MissionaryStrip(miss)
                        HorizontalDivider(Modifier.padding(vertical = 9.dp))
                    }
                    list.forEach { d ->
                        BaptismPersonCard(d, today, d.date.isBefore(today), missionariesByUnit, onOpen, embedded = true)
                    }
                }
            }
        }
    }
}

/** ONE card for ONE person being taught: date badge + countdown, unit, full notes, Golden Hour next
 *  steps, and the assigned missionaries who teach them (their unit's full-time missionaries). */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun BaptismPersonCard(
    item: Dated,
    today: LocalDate,
    overdue: Boolean,
    missionariesByUnit: Map<String, List<Missionary>>,
    onOpen: (Member) -> Unit,
    embedded: Boolean = false,
) {
    val m = item.m
    val name = m.name ?: "—"
    val unitName = (m.unitName ?: "").trim()
    val missionaries = missionariesByUnit[unitName].orEmpty()
    val note = LocalMemberNotes.current[m.personUuid]
    val steps = Milestones.nextSteps(m, today = today)
    val accent = if (overdue) OverdueOrange else MaterialTheme.colorScheme.primary

    val days = ChronoUnit.DAYS.between(today, item.date).toInt()
    val rel = when {
        overdue -> "${-days} day${if (days == -1) "" else "s"} ago"
        days == 0 -> "Today"
        days == 1 -> "Tomorrow"
        else -> "in $days days"
    }

    val body: @Composable () -> Unit = {
        Column {
            // Header: avatar + name (tappable) + date badge on the right.
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.Top) {
                Row(
                    Modifier.weight(1f).clip(RoundedCornerShape(8.dp)).clickable { onOpen(m) },
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    PhotoAvatar(name = name, photoUrl = m.photoUrl, size = 44.dp)
                    Spacer(Modifier.width(10.dp))
                    Column {
                        Text(name, fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        if (unitName.isNotEmpty()) {
                            Text(unitName, fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                    }
                }
                Spacer(Modifier.width(10.dp))
                Column(
                    modifier = Modifier.width(56.dp).clip(RoundedCornerShape(10.dp))
                        .background(accent.copy(alpha = 0.10f)).padding(vertical = 6.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    Text(Dates.monthAbbrUpper(item.date), fontSize = 11.sp, color = accent, fontWeight = FontWeight.Bold)
                    Text("${item.date.dayOfMonth}", fontSize = 22.sp, color = accent, fontWeight = FontWeight.Bold)
                    Text(Dates.weekdayAbbr(item.date), fontSize = 10.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }

            Text(
                "Planned baptism · $rel",
                fontSize = 11.sp, color = accent, fontWeight = FontWeight.SemiBold,
                modifier = Modifier.padding(top = 6.dp),
            )

            // Golden Hour chips — quick covenant-path glance + suggested next step.
            Spacer(Modifier.size(10.dp))
            GoldenHourChips(member = m, size = 22.dp, highlightNext = true, today = today)

            // Next steps (the not-yet-done Golden Hour milestones for this person).
            if (steps.isNotEmpty()) {
                Spacer(Modifier.size(10.dp))
                Text(
                    "NEXT STEPS", fontSize = 10.sp, fontWeight = FontWeight.Bold,
                    color = MaterialTheme.colorScheme.onSurfaceVariant, letterSpacing = 0.6.sp,
                )
                Spacer(Modifier.size(4.dp))
                FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    steps.forEach { ms -> NextStepChip(ms.label, ms.color) }
                }
            }

            // Full leader note / comment for this person.
            note?.let {
                Spacer(Modifier.size(10.dp))
                NoteLine(it)
            }

            // Missionary info: who teaches them (their unit's assigned missionaries). Hidden when
            // embedded in a by-unit SectionCard — that view already shows the unit's missionaries once at
            // the top, so showing them again per card would double them (web parity, fix 2026-06-18).
            if (!embedded) {
                HorizontalDivider(Modifier.padding(top = 12.dp, bottom = 10.dp))
                Text(
                    "MISSIONARIES", fontSize = 10.sp, fontWeight = FontWeight.Bold,
                    color = MaterialTheme.colorScheme.onSurfaceVariant, letterSpacing = 0.6.sp,
                )
                Spacer(Modifier.size(6.dp))
                if (missionaries.isNotEmpty()) {
                    MissionaryStrip(missionaries)
                } else {
                    Text(
                        "No assigned missionaries on record for this ward.",
                        fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }
    }

    if (embedded) {
        Box(Modifier.fillMaxWidth().padding(vertical = 8.dp)) { body() }
    } else {
        androidx.compose.material3.Card(
            modifier = Modifier.fillMaxWidth().padding(vertical = 6.dp),
            shape = RoundedCornerShape(16.dp),
            elevation = androidx.compose.material3.CardDefaults.cardElevation(0.dp),
            colors = androidx.compose.material3.CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
            border = androidx.compose.foundation.BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
        ) {
            Box(Modifier.padding(16.dp)) { body() }
        }
    }
}

@Composable
private fun NextStepChip(label: String, color: Color) {
    Box(
        Modifier.clip(RoundedCornerShape(20.dp))
            .background(MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.6f))
            .padding(horizontal = 10.dp, vertical = 5.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.size(8.dp).clip(RoundedCornerShape(50)).background(color))
            Spacer(Modifier.width(6.dp))
            Text(label, fontSize = 12.sp)
        }
    }
}

@Composable
private fun GroupHeader(title: String, icon: ImageVector, color: Color?, count: Int) {
    val accent = color ?: MaterialTheme.colorScheme.primary
    Row(
        Modifier.fillMaxWidth().padding(top = 6.dp, bottom = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(icon, contentDescription = null, tint = accent, modifier = Modifier.size(16.dp))
        Spacer(Modifier.width(6.dp))
        Text(title, color = accent, fontWeight = FontWeight.Bold, fontSize = 13.sp)
        Spacer(Modifier.width(8.dp))
        CountBadge(count)
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
