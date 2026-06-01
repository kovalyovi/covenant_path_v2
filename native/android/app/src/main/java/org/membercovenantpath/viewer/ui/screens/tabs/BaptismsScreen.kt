package org.membercovenantpath.viewer.ui.screens.tabs

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
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
import androidx.compose.material.icons.filled.EventAvailable
import androidx.compose.material.icons.filled.WarningAmber
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
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
import org.membercovenantpath.viewer.ui.components.PhotoAvatar
import org.membercovenantpath.viewer.ui.components.SectionCard
import org.membercovenantpath.viewer.ui.screens.EmptyPanel
import org.membercovenantpath.viewer.util.Dates
import java.time.LocalDate

private val OverdueOrange = Color(0xFFEF6C00) // orange.shade800

private data class Dated(val m: Member, val date: LocalDate)

/**
 * Prospective baptisms: investigators with a planned `baptism_goal_date`, as a date timeline —
 * an "overdue" block ("date passed") first, then a "Scheduled" block, each grouped by date.
 * Ported from baptisms_view.dart `_OnDateView` / `_Timeline`.
 */
@Composable
fun BaptismsScreen(
    members: List<Member>,
    missionariesByUnit: Map<String, List<Missionary>>,
    onOpen: (Member) -> Unit,
    today: LocalDate = LocalDate.now(),
) {
    val items = members
        .filter { it.isInvestigator }
        .mapNotNull { m -> DateParse.parseMemberDate(m.baptismGoalDate)?.let { Dated(m, it) } }
        .sortedBy { it.date }

    val overdue = items.filter { it.date.isBefore(today) }
    val upcoming = items.filterNot { it.date.isBefore(today) }

    LazyColumn(
        modifier = Modifier.fillMaxWidth(),
        contentPadding = androidx.compose.foundation.layout.PaddingValues(14.dp),
    ) {
        item {
            SectionHeaderRow(title = "Prospective Baptisms", count = items.size)
            Spacer(Modifier.size(8.dp))
        }
        if (items.isEmpty()) {
            item { EmptyPanel("No prospective baptisms with a planned date.") }
        }
        if (overdue.isNotEmpty()) {
            item {
                DateSectionCard(
                    title = "Needs attention — date passed",
                    icon = Icons.Filled.WarningAmber,
                    color = OverdueOrange,
                    items = overdue,
                    overdue = true,
                    today = today,
                    onOpen = onOpen,
                )
            }
        }
        if (upcoming.isNotEmpty()) {
            item {
                DateSectionCard(
                    title = "Scheduled",
                    icon = Icons.Filled.EventAvailable,
                    color = MaterialTheme.colorScheme.primary,
                    items = upcoming,
                    overdue = false,
                    today = today,
                    onOpen = onOpen,
                )
            }
        }
    }
}

@Composable
private fun SectionHeaderRow(title: String, count: Int) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Box(
            Modifier
                .padding(end = 10.dp)
                .size(width = 4.dp, height = 22.dp)
                .clip(RoundedCornerShape(2.dp))
                .background(MaterialTheme.colorScheme.primary)
        )
        Text(title, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
        Spacer(Modifier.width(8.dp))
        org.membercovenantpath.viewer.ui.components.CountBadge(count)
    }
}

@Composable
private fun DateSectionCard(
    title: String,
    icon: ImageVector,
    color: Color,
    items: List<Dated>,
    overdue: Boolean,
    today: LocalDate,
    onOpen: (Member) -> Unit,
) {
    // Group by date; soonest first (overdue: oldest-passed first).
    val byDate = items.groupBy { it.date }.toSortedMap()
    SectionCard(title = title, leadingIcon = icon, iconColor = color) {
        Column {
            byDate.entries.forEachIndexed { i, (date, people) ->
                if (i > 0) HorizontalDivider(
                    Modifier.padding(vertical = 9.dp),
                    color = MaterialTheme.colorScheme.outlineVariant,
                )
                DateRow(date = date, people = people, overdue = overdue, today = today, onOpen = onOpen)
            }
        }
    }
}

/** One date in the rail: a month/day block on the left, the people for that day on the right. */
@Composable
private fun DateRow(
    date: LocalDate,
    people: List<Dated>,
    overdue: Boolean,
    today: LocalDate,
    onOpen: (Member) -> Unit,
) {
    val accent = if (overdue) OverdueOrange else MaterialTheme.colorScheme.primary
    val days = java.time.temporal.ChronoUnit.DAYS.between(today, date).toInt()
    val rel = when {
        overdue -> "${-days} day${if (days == -1) "" else "s"} ago"
        days == 0 -> "Today"
        days == 1 -> "Tomorrow"
        else -> "in $days days"
    }
    Row(verticalAlignment = Alignment.Top) {
        // date block
        Column(
            modifier = Modifier
                .width(54.dp)
                .clip(RoundedCornerShape(10.dp))
                .background(accent.copy(alpha = 0.10f))
                .padding(vertical = 6.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text(Dates.monthAbbrUpper(date), fontSize = 11.sp, color = accent, fontWeight = FontWeight.Bold)
            Text("${date.dayOfMonth}", fontSize = 22.sp, color = accent, fontWeight = FontWeight.Bold)
            Text(Dates.weekdayAbbr(date), fontSize = 10.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Text(
                rel,
                fontSize = 11.sp,
                color = if (overdue) accent else MaterialTheme.colorScheme.onSurfaceVariant,
                fontWeight = FontWeight.SemiBold,
                modifier = Modifier.padding(top = 3.dp, bottom = 1.dp),
            )
            people.forEach { p ->
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clip(RoundedCornerShape(8.dp))
                        .clickable { onOpen(p.m) }
                        .padding(vertical = 5.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    PhotoAvatar(name = p.m.name ?: "?", photoUrl = p.m.photoUrl, size = 36.dp)
                    Spacer(Modifier.width(10.dp))
                    Column(Modifier.weight(1f)) {
                        Text(p.m.name ?: "—", fontWeight = FontWeight.SemiBold)
                        Text(
                            p.m.unitName ?: "",
                            fontSize = 12.sp,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, contentDescription = null, modifier = Modifier.size(18.dp))
                }
            }
        }
    }
}
