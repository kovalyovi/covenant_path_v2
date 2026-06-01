package org.membercovenantpath.viewer.ui.screens.tabs

import androidx.compose.ui.draw.clip
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
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
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.MenuBook
import androidx.compose.material.icons.filled.VerifiedUser
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
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
import androidx.compose.runtime.toMutableStateList
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import org.membercovenantpath.viewer.logic.DateParse
import org.membercovenantpath.viewer.logic.Milestones
import org.membercovenantpath.viewer.logic.OrgBucket
import org.membercovenantpath.viewer.logic.Orgs
import org.membercovenantpath.viewer.model.Member
import org.membercovenantpath.viewer.ui.components.CountBadge
import org.membercovenantpath.viewer.ui.components.MemberRow
import org.membercovenantpath.viewer.ui.components.OrgFilterBar
import org.membercovenantpath.viewer.ui.components.SectionCard
import org.membercovenantpath.viewer.ui.screens.EmptyPanel
import java.time.LocalDate
import java.time.temporal.ChronoUnit

private enum class GhSection { NewMembers, BeingTaught }
private enum class Window(val label: String) { Week("Week"), Month("Month"), Year("Year"), All("All") }

/**
 * Golden Hour tab: segmented **New Members** (baptized; completion summary + milestone chips +
 * org filter + recency window) and **Being Taught** (investigators). Ported from
 * golden_hour_view.dart `_GoldenHourView`.
 */
@Composable
fun GoldenHourScreen(
    members: List<Member>,
    onOpen: (Member) -> Unit,
    today: LocalDate = LocalDate.now(),
) {
    var section by remember { mutableStateOf(GhSection.NewMembers) }
    var window by remember { mutableStateOf(Window.All) }
    val orgs = remember { OrgBucket.entries.toMutableStateList() }

    fun toggleOrg(b: OrgBucket) {
        if (b in orgs) { if (orgs.size > 1) orgs.remove(b) } else orgs.add(b)
    }

    val newMembers = remember(members) { members.filterNot { it.isInvestigator } }
    val beingTaught = remember(members) { members.filter { it.isInvestigator } }

    LazyColumn(
        modifier = Modifier.fillMaxWidth(),
        contentPadding = PaddingValues(14.dp),
    ) {
        item {
            SectionToggle(
                section = section,
                newCount = newMembers.size,
                taughtCount = beingTaught.size,
                onChange = { section = it },
            )
            Spacer(Modifier.size(8.dp))
        }

        if (section == GhSection.BeingTaught) {
            item { HeaderBar("Being Taught", beingTaught.size) }
            if (beingTaught.isEmpty()) {
                item { EmptyPanel("No one currently being taught.") }
            } else {
                val sorted = beingTaught.sortedWith(byDate("baptism_goal_date", ascending = true))
                memberRows(sorted, onOpen, chips = false, dateField = "baptism_goal_date", today = today)
            }
            return@LazyColumn
        }

        // New Members
        val allOrgs = orgs.size == OrgBucket.entries.size
        val rows = newMembers
            .filter { within(it, window, today) }
            .filter { allOrgs || Orgs.responsibleOrg(it, today) in orgs }

        item {
            OrgFilterBar(
                selected = orgs.toSet(),
                onToggle = ::toggleOrg,
                onClear = { orgs.clear(); orgs.addAll(OrgBucket.entries) },
                modifier = Modifier.fillMaxWidth(),
            )
            if (!allOrgs && orgs.size == 1) {
                Spacer(Modifier.size(6.dp))
                Text(
                    Orgs.responsibilityNote(orgs.first()),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    textAlign = TextAlign.Center,
                    modifier = Modifier.fillMaxWidth().padding(horizontal = 20.dp),
                )
            }
            Spacer(Modifier.size(10.dp))
            WindowSelector(window) { window = it }
            Spacer(Modifier.size(10.dp))
            HeaderBar("Recently Baptized", rows.size)
        }

        item { CompletionCard(rows, onOpen, today) }

        if (rows.isEmpty()) {
            item { EmptyPanel("No new members in this window.") }
        } else {
            val sorted = rows.sortedWith(byDate("baptism_date", ascending = false))
            memberRows(sorted, onOpen, chips = true, dateField = "baptism_date", today = today)
        }
    }
}

private fun within(m: Member, window: Window, today: LocalDate): Boolean {
    if (window == Window.All) return true
    val d = DateParse.parseMemberDate(m.baptismDate) ?: return false
    val days = ChronoUnit.DAYS.between(d, today)
    return when (window) {
        Window.Week -> days <= 7
        Window.Month -> days <= 31
        Window.Year -> days <= 366
        Window.All -> true
    }
}

private fun byDate(field: String, ascending: Boolean): Comparator<Member> = Comparator { a, b ->
    val da = DateParse.parseMemberDate(if (field == "baptism_date") a.baptismDate else a.baptismGoalDate)
    val db = DateParse.parseMemberDate(if (field == "baptism_date") b.baptismDate else b.baptismGoalDate)
    when {
        da == null -> 1
        db == null -> -1
        else -> if (ascending) da.compareTo(db) else db.compareTo(da)
    }
}

@Composable
private fun SectionToggle(
    section: GhSection,
    newCount: Int,
    taughtCount: Int,
    onChange: (GhSection) -> Unit,
) {
    SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth()) {
        SegmentedButton(
            selected = section == GhSection.NewMembers,
            onClick = { onChange(GhSection.NewMembers) },
            shape = SegmentedButtonDefaults.itemShape(0, 2),
            icon = { Icon(Icons.Filled.VerifiedUser, contentDescription = null, modifier = Modifier.size(18.dp)) },
        ) { Text("New Members ($newCount)", maxLines = 1, overflow = TextOverflow.Ellipsis) }
        SegmentedButton(
            selected = section == GhSection.BeingTaught,
            onClick = { onChange(GhSection.BeingTaught) },
            shape = SegmentedButtonDefaults.itemShape(1, 2),
            icon = { Icon(Icons.AutoMirrored.Filled.MenuBook, contentDescription = null, modifier = Modifier.size(18.dp)) },
        ) { Text("Being Taught ($taughtCount)", maxLines = 1, overflow = TextOverflow.Ellipsis) }
    }
}

@Composable
private fun WindowSelector(window: Window, onChange: (Window) -> Unit) {
    SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth()) {
        Window.entries.forEachIndexed { i, w ->
            SegmentedButton(
                selected = window == w,
                onClick = { onChange(w) },
                shape = SegmentedButtonDefaults.itemShape(i, Window.entries.size),
            ) { Text(w.label) }
        }
    }
}

@Composable
private fun HeaderBar(title: String, count: Int) {
    Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(vertical = 4.dp)) {
        Text(title, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
        Spacer(Modifier.width(8.dp))
        CountBadge(count)
    }
}

/**
 * Member list emitted as INDIVIDUAL lazy items (only on-screen rows compose) instead of an eager
 * Column inside a single item — so switching into Golden Hour with a full stake (100+ baptized, each
 * row computing 6 milestone chips + a photo) no longer builds every row up front. That eager build was
 * the Baptisms↔Golden Hour navigation lag. Keeps the "By date" section header; rows keep dividers.
 */
private fun LazyListScope.memberRows(
    rows: List<Member>,
    onOpen: (Member) -> Unit,
    chips: Boolean,
    dateField: String,
    today: LocalDate,
) {
    item(key = "by-date-header-$dateField") {
        Text(
            "By date",
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.Bold,
            modifier = Modifier.padding(top = 14.dp, bottom = 2.dp),
        )
    }
    itemsIndexed(rows, key = { _, m -> m.personUuid ?: m.name ?: m.hashCode().toString() }) { i, m ->
        Column {
            if (i > 0) HorizontalDivider()
            MemberRow(
                member = m,
                onOpen = onOpen,
                chips = chips,
                showUnit = true,
                dateField = dateField,
                today = today,
            )
        }
    }
}

/**
 * Golden Hour completion: % per milestone among the ELIGIBLE only (so ineligible people never drag
 * the number down). Tapping a stat shows who's still missing it. Ported from `_CompletionCard`.
 */
@Composable
private fun CompletionCard(rows: List<Member>, onOpen: (Member) -> Unit, today: LocalDate) {
    if (rows.isEmpty()) return
    var sheetFor by remember { mutableStateOf<Pair<String, List<Member>>?>(null) }

    SectionCard(title = "Golden Hour completion") {
        @OptIn(ExperimentalLayoutApi::class)
        FlowRow(
            horizontalArrangement = Arrangement.spacedBy(18.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Milestones.all.forEach { ms ->
                val eligible = rows.filter { ms.eligible(it, today) }
                if (eligible.isEmpty()) return@forEach
                val done = eligible.filter { ms.complete(it) }
                val missing = eligible.filterNot { ms.complete(it) }
                PctStat(
                    label = ms.label,
                    pct = done.size.toFloat() / eligible.size,
                    caption = "${done.size}/${eligible.size}",
                    onClick = { sheetFor = ms.label to missing },
                )
            }
        }
    }

    sheetFor?.let { (label, missing) ->
        MissingSheet(label = label, missing = missing, onOpen = onOpen, onDismiss = { sheetFor = null })
    }
}

@Composable
private fun PctStat(label: String, pct: Float, caption: String, onClick: () -> Unit) {
    Column(
        modifier = Modifier
            .width(124.dp)
            .clip(RoundedCornerShape(8.dp))
            .clickable(onClick = onClick),
    ) {
        Row(verticalAlignment = Alignment.Bottom) {
            Text("${(pct * 100).toInt()}%", style = MaterialTheme.typography.titleLarge)
            Spacer(Modifier.width(4.dp))
            Text(caption, style = MaterialTheme.typography.bodySmall)
        }
        Text(label, style = MaterialTheme.typography.bodySmall, maxLines = 1, overflow = TextOverflow.Ellipsis)
        Spacer(Modifier.size(4.dp))
        LinearProgressIndicator(
            progress = { pct.coerceIn(0f, 1f) },
            modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(4.dp)),
        )
    }
}
