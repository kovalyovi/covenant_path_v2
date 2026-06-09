package org.membercovenantpath.viewer.ui.screens.tabs

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Apartment
import androidx.compose.material.icons.filled.ArrowDownward
import androidx.compose.material.icons.filled.ArrowDropDown
import androidx.compose.material.icons.filled.ArrowUpward
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Sort
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.toMutableStateList
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import org.membercovenantpath.viewer.logic.DateParse
import org.membercovenantpath.viewer.logic.Milestone
import org.membercovenantpath.viewer.logic.Milestones
import org.membercovenantpath.viewer.logic.OrgBucket
import org.membercovenantpath.viewer.logic.Orgs
import org.membercovenantpath.viewer.model.Member
import org.membercovenantpath.viewer.ui.components.CountBadge
import org.membercovenantpath.viewer.ui.components.MemberRow
import org.membercovenantpath.viewer.ui.components.OrgFilterBar
import org.membercovenantpath.viewer.ui.components.BigHeader
import org.membercovenantpath.viewer.ui.components.SectionCard
import org.membercovenantpath.viewer.ui.theme.StatusColors
import org.membercovenantpath.viewer.ui.theme.unitColor
import org.membercovenantpath.viewer.ui.theme.unitColorMap
import java.time.LocalDate

/**
 * Needs Action: a category selector (one milestone at a time, each with its outstanding count),
 * then the ELIGIBLE members still missing that step, with a per-unit breakdown. Same org filter as
 * Golden Hour. Ported from needs_view.dart `_NeedsView`.
 */
@Composable
fun NeedsScreen(
    members: List<Member>,
    onOpen: (Member) -> Unit,
    today: LocalDate = LocalDate.now(),
) {
    var selected by remember { mutableStateOf<Int?>(null) }
    var ascending by remember { mutableStateOf(true) } // oldest-baptized (most overdue) first
    val orgs = remember { OrgBucket.entries.toMutableStateList() }
    var ward by remember { mutableStateOf<String?>(null) } // null = Stake (all wards)
    val wards = remember(members) {
        members.filterNot { it.isInvestigator }.mapNotNull { it.unitName }.filter { it.isNotEmpty() }.distinct().sorted()
    }
    // One distinct color per ward, assigned over ALL units (stable as org/category filters change).
    val unitColors = remember(members) { unitColorMap(members.map { it.unitName ?: "—" }) }

    fun toggleOrg(b: OrgBucket) {
        if (b in orgs) { if (orgs.size > 1) orgs.remove(b) } else orgs.add(b)
    }

    val allOrgs = orgs.size == OrgBucket.entries.size
    val orgScoped = members.filterNot { it.isInvestigator }
        .let { if (allOrgs) it else it.filter { m -> Orgs.responsibleOrg(m, today) in orgs } }
    // Ward dropdown (default Stake = all wards) filters on top of the org filter.
    val baptized = if (ward == null) orgScoped else orgScoped.filter { (it.unitName ?: "") == ward }

    val cmp = Comparator<Member> { a, b ->
        val da = DateParse.parseMemberDate(a.baptismDate)
        val db = DateParse.parseMemberDate(b.baptismDate)
        var c = when {
            da == null && db == null -> 0
            da == null -> 1
            db == null -> -1
            else -> da.compareTo(db)
        }
        if (c == 0) c = (a.unitName ?: "").compareTo(b.unitName ?: "")
        if (ascending) c else -c
    }

    val missingByMs: List<List<Member>> = Milestones.needsCategories.map { ms ->
        baptized.filter { ms.eligible(it, today) && !ms.complete(it) }.sortedWith(cmp)
    }
    val total = missingByMs.sumOf { it.size }

    LazyColumn(modifier = Modifier.fillMaxWidth(), contentPadding = androidx.compose.foundation.layout.PaddingValues(14.dp)) {
        item {
            BigHeader("Needs Action", "Eligible members still missing each integration step")
            Spacer(Modifier.size(10.dp))
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
            if (wards.size > 1) {
                Spacer(Modifier.size(8.dp))
                WardDropdown(wards = wards, ward = ward, onSelect = { ward = it })
            }
        }

        if (total == 0) {
            item {
                Box(Modifier.fillMaxWidth().padding(32.dp), contentAlignment = Alignment.Center) {
                    Text(
                        if (allOrgs) "Nothing outstanding — everyone eligible is on track."
                        else "Nothing outstanding for the selected orgs.",
                        textAlign = TextAlign.Center,
                    )
                }
            }
            return@LazyColumn
        }

        val firstNonEmpty = missingByMs.indexOfFirst { it.isNotEmpty() }
        val sel = selected ?: (if (firstNonEmpty < 0) 0 else firstNonEmpty)
        val ms = Milestones.needsCategories[sel]
        val missing = missingByMs[sel]

        item {
            Spacer(Modifier.size(12.dp))
            Row(Modifier.horizontalScroll(rememberScrollState())) {
                Milestones.needsCategories.forEachIndexed { i, m ->
                    if (i > 0) Spacer(Modifier.width(8.dp))
                    CategoryChip(
                        ms = m,
                        count = missingByMs[i].size,
                        selected = i == sel,
                        onClick = { selected = i },
                    )
                }
            }
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Filled.Sort, contentDescription = null, tint = StatusColors.GreyText, modifier = Modifier.size(15.dp))
                Spacer(Modifier.width(6.dp))
                Text(
                    "Baptism date, then unit",
                    style = MaterialTheme.typography.bodySmall,
                    color = StatusColors.GreyText,
                )
                IconButton(onClick = { ascending = !ascending }) {
                    Icon(
                        if (ascending) Icons.Filled.ArrowUpward else Icons.Filled.ArrowDownward,
                        contentDescription = "Toggle sort",
                        modifier = Modifier.size(18.dp),
                    )
                }
            }
        }

        item { CategorySection(ms = ms, missing = missing, onOpen = onOpen, today = today, unitColors = unitColors) }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun CategorySection(
    ms: Milestone,
    missing: List<Member>,
    onOpen: (Member) -> Unit,
    today: LocalDate,
    unitColors: Map<String, Color>,
) {
    val byUnit = missing.groupingBy { it.unitName ?: "—" }.eachCount()
        .entries.sortedByDescending { it.value }
    SectionCard(
        title = "Needs ${ms.label}",
        leadingIcon = ms.icon,
        iconColor = ms.color,
        trailing = { CountBadge(missing.size) },
    ) {
        Column {
            FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                byUnit.forEach { (unit, count) -> UnitCountChip(unit, count, unitColors[unit] ?: unitColor(unit)) }
            }
            HorizontalDivider(Modifier.padding(vertical = 8.dp))
            missing.forEachIndexed { i, m ->
                if (i > 0) HorizontalDivider()
                MemberRow(member = m, onOpen = onOpen, showUnit = true, showResp = true, today = today)
            }
        }
    }
}

@Composable
private fun UnitCountChip(unit: String, count: Int, color: Color) {
    Surface(
        color = color.copy(alpha = 0.10f),
        shape = RoundedCornerShape(20.dp),
        border = BorderStroke(1.dp, color.copy(alpha = 0.35f)),
    ) {
        Text(
            "$unit · $count",
            color = color,
            fontSize = 12.sp,
            fontWeight = FontWeight.SemiBold,
            modifier = Modifier.padding(horizontal = 10.dp, vertical = 4.dp),
        )
    }
}

@Composable
private fun CategoryChip(ms: Milestone, count: Int, selected: Boolean, onClick: () -> Unit) {
    val done = count == 0
    val base = if (done) StatusColors.GreyBorder else ms.color
    val fg = if (selected) Color.White else base
    Surface(
        color = if (selected) base else base.copy(alpha = 0.10f),
        shape = RoundedCornerShape(20.dp),
        border = BorderStroke(1.dp, base.copy(alpha = if (selected) 1f else 0.35f)),
        modifier = Modifier.clip(RoundedCornerShape(20.dp)).clickable(onClick = onClick),
    ) {
        Row(
            verticalAlignment = Alignment.CenterVertically,
            modifier = Modifier.padding(horizontal = 14.dp, vertical = 9.dp),
        ) {
            Icon(
                if (done) Icons.Filled.CheckCircle else ms.icon,
                contentDescription = null,
                tint = fg,
                modifier = Modifier.size(17.dp),
            )
            Spacer(Modifier.width(7.dp))
            Text(ms.label, color = fg, fontWeight = FontWeight.SemiBold, fontSize = 13.sp)
            if (!done) {
                Spacer(Modifier.width(7.dp))
                Surface(
                    color = if (selected) Color.White.copy(alpha = 0.25f) else base.copy(alpha = 0.16f),
                    shape = RoundedCornerShape(20.dp),
                ) {
                    Text(
                        "$count",
                        color = fg,
                        fontWeight = FontWeight.Bold,
                        fontSize = 12.sp,
                        modifier = Modifier.padding(horizontal = 7.dp, vertical = 1.dp),
                    )
                }
            }
        }
    }
}

/** Ward picker below the org filters — one ward or the whole stake (default). The caller hides it
 *  when there's only one unit in view. */
@Composable
private fun WardDropdown(wards: List<String>, ward: String?, onSelect: (String?) -> Unit) {
    var expanded by remember { mutableStateOf(false) }
    Box {
        Surface(
            color = MaterialTheme.colorScheme.surface,
            shape = RoundedCornerShape(10.dp),
            border = BorderStroke(1.dp, MaterialTheme.colorScheme.outline),
            modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).clickable { expanded = true },
        ) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier.padding(horizontal = 12.dp, vertical = 10.dp),
            ) {
                Icon(
                    Icons.Filled.Apartment, contentDescription = null,
                    tint = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.size(18.dp),
                )
                Spacer(Modifier.width(8.dp))
                Text(ward ?: "Stake — all wards", style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
                Icon(Icons.Filled.ArrowDropDown, contentDescription = null)
            }
        }
        DropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
            DropdownMenuItem(text = { Text("Stake — all wards") }, onClick = { onSelect(null); expanded = false })
            wards.forEach { w ->
                DropdownMenuItem(text = { Text(w) }, onClick = { onSelect(w); expanded = false })
            }
        }
    }
}
