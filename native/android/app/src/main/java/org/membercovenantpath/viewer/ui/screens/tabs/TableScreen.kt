package org.membercovenantpath.viewer.ui.screens.tabs

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.StickyNote2
import androidx.compose.material.icons.filled.ArrowDownward
import androidx.compose.material.icons.filled.ArrowUpward
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.FilterList
import androidx.compose.material.icons.filled.UnfoldMore
import androidx.compose.material.icons.filled.WarningAmber
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Checkbox
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import org.membercovenantpath.viewer.logic.Milestones
import org.membercovenantpath.viewer.model.Member
import org.membercovenantpath.viewer.ui.theme.StatusColors

/**
 * Every covenant-path field in a sortable, color-coded grid (Yes=green / No=red / N/A=grey,
 * recommend Active/Expired/No, sex M/F). 3-state sort on text columns + a per-column value filter on
 * every column (tap the header funnel). Ported from table_view.dart `_SpreadsheetView`.
 *
 * Covenant-path status cells honor the shared display contract (`FieldDisplay`): a real value shows
 * verbatim, "N/A" shows quietly (not eligible), and a DATA ISSUE — the needs-profile-api / blocked
 * sentinel OR an empty value — shows a warning indicator (never the raw sentinel string; an admin may
 * see it). This is the surface the user was complaining leaked the raw "needs-profile-api" string.
 */
@Composable
fun TableScreen(members: List<Member>, onOpen: (Member) -> Unit, isAdmin: Boolean = false) {
    var sortCol by remember { mutableStateOf<Int?>(null) }
    var sortAsc by remember { mutableStateOf(true) }
    // Per-column value filters: column index -> the set of allowed cell values (absent = unfiltered).
    val filters = remember { mutableStateMapOf<Int, Set<String>>() }
    var filterFor by remember { mutableStateOf<Int?>(null) } // column whose filter dialog is open

    val base = members.filterNot { it.isInvestigator }
    val rows = base
        .filter { m -> filters.all { (ci, allowed) -> Columns[ci].value(m) in allowed } }
        .let { list ->
            val col = sortCol ?: return@let list
            val key = Columns[col]
            val sorted = if (key.header == "Age") { // age sorts numerically, not as a string
                list.sortedBy { org.membercovenantpath.viewer.logic.Milestones.ageYears(it) ?: -1 }
            } else {
                list.sortedWith(compareBy(String.CASE_INSENSITIVE_ORDER) { key.value(it) })
            }
            sorted.let { if (sortAsc) it else it.reversed() }
        }

    fun onSort(col: Int) {
        if (sortCol == col) {
            if (sortAsc) sortAsc = false else sortCol = null
        } else { sortCol = col; sortAsc = true }
    }

    val hScroll = rememberScrollState()
    Column(Modifier.fillMaxSize()) {
        Row(
            Modifier.fillMaxWidth().padding(start = 12.dp, end = 8.dp, top = 8.dp, bottom = 4.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                "${rows.size} member${if (rows.size == 1) "" else "s"}" +
                    (if (filters.isNotEmpty()) "  ·  filtered" else ""),
                style = MaterialTheme.typography.bodySmall,
            )
            Spacer(Modifier.weight(1f))
            if (filters.isNotEmpty()) {
                TextButton(onClick = { filters.clear() }) {
                    Icon(Icons.Filled.Close, contentDescription = null, modifier = Modifier.size(15.dp))
                    Spacer(Modifier.width(4.dp))
                    Text("Clear filters")
                }
            }
        }
        // Header row (sticky-ish: lives above the scrolling body, shares the same horizontal scroll).
        Row(
            Modifier
                .fillMaxWidth()
                .background(MaterialTheme.colorScheme.primary)
                .horizontalScroll(hScroll)
                .padding(vertical = 12.dp),
        ) {
            Cell("#", NumWidth, header = true)
            Columns.forEachIndexed { i, c ->
                HeaderCell(
                    label = c.header,
                    width = c.width,
                    sortable = c.kind == Kind.TEXT,
                    sortState = if (sortCol == i) (if (sortAsc) 1 else -1) else 0,
                    onSort = { onSort(i) },
                    filtered = filters.containsKey(i),
                    onFilter = { filterFor = i },
                )
            }
        }
        LazyColumn(Modifier.fillMaxWidth().weight(1f)) {
            itemsIndexed(rows, key = { _, m -> m.personUuid ?: m.name ?: m.hashCode().toString() }) { idx, m ->
                Row(
                    Modifier
                        .fillMaxWidth()
                        .clickable { onOpen(m) }
                        .horizontalScroll(hScroll)
                        .padding(vertical = 8.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Cell("${idx + 1}", NumWidth, color = StatusColors.GreyText)
                    Columns.forEach { c ->
                        // The Member column shows a short "First L" name; its FULL value still drives
                        // sort/filter (computed above). Other columns render their value verbatim.
                        val shown = if (c.header == "Member") shortMemberName(c.value(m)) else c.value(m)
                        // The Member cell carries a note marker when leaders left notes on this person.
                        if (c.header == "Member" &&
                            org.membercovenantpath.viewer.ui.components.LocalMemberNotes
                                .current.containsKey(m.personUuid)
                        ) {
                            Row(Modifier.width(c.width).padding(horizontal = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                                Text(
                                    shown, fontSize = 12.sp, maxLines = 1,
                                    overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis,
                                    modifier = Modifier.weight(1f, fill = false),
                                )
                                Spacer(Modifier.width(4.dp))
                                Icon(
                                    Icons.AutoMirrored.Filled.StickyNote2,
                                    contentDescription = "Has notes",
                                    tint = MaterialTheme.colorScheme.primary,
                                    modifier = Modifier.size(13.dp),
                                )
                            }
                        } else {
                            ValueCell(shown, c.kind, c.width, isAdmin)
                        }
                    }
                }
            }
        }
    }

    // Per-column filter dialog: distinct values come from the unfiltered base so options never vanish.
    filterFor?.let { col ->
        val c = Columns[col]
        val options = remember(col, members) {
            base.map { c.value(it) }.distinct().sortedWith(String.CASE_INSENSITIVE_ORDER)
        }
        // For covenant-path status columns, the filter menu shows a friendly label for the data-issue
        // group (sentinel/empty) instead of the raw "needs-profile-api" string — leaders never see it.
        val labelOf: (String) -> String = label@{ raw ->
            if (c.kind == Kind.YESNO || c.kind == Kind.RECOMMEND) {
                val r = org.membercovenantpath.viewer.logic.FieldDisplay.classify(raw, isAdmin)
                return@label when (r.status) {
                    org.membercovenantpath.viewer.logic.FieldDisplay.Status.ISSUE ->
                        if (r.text.isNotEmpty()) "Needs data ($raw)" else "Needs data"
                    org.membercovenantpath.viewer.logic.FieldDisplay.Status.NA -> "N/A"
                    org.membercovenantpath.viewer.logic.FieldDisplay.Status.VALUE -> r.text
                }
            }
            if (raw.isBlank()) "(blank)" else raw
        }
        FilterDialog(
            title = c.header,
            options = options,
            labelOf = labelOf,
            initial = filters[col] ?: options.toSet(),
            onApply = { sel ->
                // All or none selected = no filter; otherwise keep just the chosen values.
                if (sel.isEmpty() || sel.size == options.size) filters.remove(col) else filters[col] = sel
                filterFor = null
            },
            onDismiss = { filterFor = null },
        )
    }
}

private val NumWidth = 36.dp

@Composable
private fun HeaderCell(
    label: String,
    width: Dp,
    sortable: Boolean,
    sortState: Int,
    onSort: () -> Unit,
    filtered: Boolean,
    onFilter: () -> Unit,
) {
    Row(
        modifier = Modifier.width(width).padding(horizontal = 7.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            label,
            color = MaterialTheme.colorScheme.onPrimary,
            fontWeight = FontWeight.Bold,
            fontSize = 13.sp,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.weight(1f, fill = false),
        )
        if (sortable) {
            Spacer(Modifier.width(2.dp))
            Icon(
                when (sortState) {
                    1 -> Icons.Filled.ArrowUpward
                    -1 -> Icons.Filled.ArrowDownward
                    else -> Icons.Filled.UnfoldMore
                },
                contentDescription = "Sort",
                tint = MaterialTheme.colorScheme.onPrimary.copy(alpha = if (sortState == 0) 0.55f else 1f),
                modifier = Modifier.size(14.dp).clickable(onClick = onSort),
            )
        }
        Spacer(Modifier.width(2.dp))
        Icon(
            Icons.Filled.FilterList,
            contentDescription = "Filter $label",
            tint = MaterialTheme.colorScheme.onPrimary.copy(alpha = if (filtered) 1f else 0.45f),
            modifier = Modifier.size(14.dp).clickable(onClick = onFilter),
        )
    }
}

@Composable
private fun Cell(text: String, width: Dp, header: Boolean = false, color: Color = Color.Unspecified) {
    Text(
        text,
        modifier = Modifier.width(width).padding(horizontal = 7.dp),
        fontSize = 13.sp,
        color = if (header) MaterialTheme.colorScheme.onPrimary else color,
        fontWeight = if (header) FontWeight.Bold else FontWeight.Normal,
        maxLines = 1,
    )
}

@Composable
private fun ValueCell(value: String, kind: Kind, width: Dp, isAdmin: Boolean) {
    // Covenant-path status columns route through the shared display contract so the raw
    // "needs-profile-api" / "blocked: …" sentinel (or an empty value) never leaks — a DATA ISSUE shows
    // a warning indicator (a leader sees no text; an admin sees the raw string to diagnose). N/A shows
    // quietly. A real value keeps the existing color fill. Other column kinds are unchanged.
    if (kind == Kind.YESNO || kind == Kind.RECOMMEND) {
        val r = org.membercovenantpath.viewer.logic.FieldDisplay.classify(value, isAdmin)
        Box(Modifier.width(width).padding(horizontal = 7.dp)) {
            when (r.status) {
                org.membercovenantpath.viewer.logic.FieldDisplay.Status.ISSUE ->
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(
                            androidx.compose.material.icons.Icons.Filled.WarningAmber,
                            contentDescription = "Data issue — value unavailable",
                            tint = StatusColors.NextAmber,
                            modifier = Modifier.size(15.dp),
                        )
                        if (r.text.isNotEmpty()) { // admin-only raw sentinel, for diagnosis
                            Spacer(Modifier.width(4.dp))
                            Text(
                                r.text, fontSize = 11.sp, color = StatusColors.GreyText,
                                maxLines = 1, overflow = TextOverflow.Ellipsis,
                            )
                        }
                    }
                org.membercovenantpath.viewer.logic.FieldDisplay.Status.NA ->
                    Box(
                        Modifier.clip(RoundedCornerShape(6.dp)).background(StatusColors.CellGrey)
                            .padding(horizontal = 8.dp, vertical = 4.dp),
                    ) { Text("N/A", fontSize = 13.sp, color = StatusColors.GreyText, maxLines = 1) }
                org.membercovenantpath.viewer.logic.FieldDisplay.Status.VALUE -> {
                    val fill = cellColor(r.text, kind)
                    if (fill == null) Text(r.text, fontSize = 13.sp, maxLines = 1)
                    else Box(
                        Modifier.clip(RoundedCornerShape(6.dp)).background(fill)
                            .padding(horizontal = 8.dp, vertical = 4.dp),
                    ) { Text(r.text, fontSize = 13.sp, fontWeight = FontWeight.Medium, maxLines = 1) }
                }
            }
        }
        return
    }

    val fill = cellColor(value, kind)
    Box(Modifier.width(width).padding(horizontal = 7.dp)) {
        if (fill == null) {
            Text(value, fontSize = 13.sp, maxLines = 1)
        } else {
            Box(
                Modifier
                    .clip(RoundedCornerShape(6.dp))
                    .background(fill)
                    .padding(horizontal = 8.dp, vertical = 4.dp),
            ) {
                Text(value, fontSize = 13.sp, fontWeight = FontWeight.Medium, maxLines = 1)
            }
        }
    }
}

/** Table-only short name: "First L" — first name + last initial, dropping any middle name
 *  ("Kovaliov, Ilya James" -> "Ilya K"). Names arrive "Last, First [Middle…]"; only the rendered
 *  cell text is shortened — sort/filter keep the full value (mirrors web abbreviateName). */
private fun shortMemberName(n: String): String {
    val comma = n.indexOf(',')
    if (comma <= 0) return n
    val last = n.substring(0, comma).trim()
    val first = n.substring(comma + 1).trim().split(Regex("\\s+")).firstOrNull().orEmpty()
    return if (last.isNotEmpty() && first.isNotEmpty()) "$first ${last[0]}" else n
}

private fun cellColor(v: String, kind: Kind): Color? = when (kind) {
    Kind.YESNO -> when (v) {
        "Yes" -> StatusColors.CellGreen
        "No" -> StatusColors.CellRed
        "N/A" -> StatusColors.CellGrey
        else -> null
    }
    Kind.RECOMMEND -> when (v) {
        "Active" -> StatusColors.CellGreen
        "Expired" -> StatusColors.CellAmber
        "No" -> StatusColors.CellRed
        else -> null
    }
    Kind.GENDER -> when (v) {
        "M" -> StatusColors.CellMaleBlue
        "F" -> StatusColors.CellFemalePink
        else -> null
    }
    Kind.FRIENDS -> {
        val n = v.toIntOrNull()
        when {
            n != null -> if (n > 0) StatusColors.CellGreen else StatusColors.CellRed
            v == "Yes" -> StatusColors.CellGreen
            v == "No" -> StatusColors.CellRed
            else -> null
        }
    }
    Kind.TEXT -> null
}

/** A multi-select value picker for one column: check the values to keep, then Apply. [labelOf] maps a
 *  raw cell value to the label shown (so a data-issue sentinel reads "Needs data", not the raw string);
 *  the filter still keys on the raw value. */
@Composable
private fun FilterDialog(
    title: String,
    options: List<String>,
    labelOf: (String) -> String = { if (it.isBlank()) "(blank)" else it },
    initial: Set<String>,
    onApply: (Set<String>) -> Unit,
    onDismiss: () -> Unit,
) {
    val checked = remember { mutableStateListOf<String>().apply { addAll(initial) } }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Filter · $title") },
        text = {
            Column(Modifier.heightIn(max = 360.dp).verticalScroll(rememberScrollState())) {
                Row {
                    TextButton(onClick = { checked.clear(); checked.addAll(options) }) { Text("All") }
                    TextButton(onClick = { checked.clear() }) { Text("None") }
                }
                options.forEach { opt ->
                    Row(
                        Modifier.fillMaxWidth().clickable {
                            if (opt in checked) checked.remove(opt) else checked.add(opt)
                        },
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Checkbox(
                            checked = opt in checked,
                            onCheckedChange = { if (it) checked.add(opt) else checked.remove(opt) },
                        )
                        Text(labelOf(opt))
                    }
                }
            }
        },
        confirmButton = { TextButton(onClick = { onApply(checked.toSet()) }) { Text("Apply") } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}

private enum class Kind { TEXT, YESNO, RECOMMEND, GENDER, FRIENDS }

private data class Col(val header: String, val kind: Kind, val width: Dp, val value: (Member) -> String)

/** Column set mirroring table_view.dart `_cols`. Widths leave room for the header sort/filter icons. */
private val Columns: List<Col> = listOf(
    Col("Member", Kind.TEXT, 158.dp) { it.name ?: "" },
    Col("Sex", Kind.GENDER, 66.dp) { it.sex ?: "" },
    Col("Age", Kind.TEXT, 64.dp) { org.membercovenantpath.viewer.logic.Milestones.ageYears(it)?.toString() ?: "" },
    Col("Unit", Kind.TEXT, 140.dp) { it.unitName ?: "" },
    Col("Baptism", Kind.TEXT, 112.dp) { it.baptismDate ?: "" },
    Col("Member for", Kind.TEXT, 132.dp) {
        (it.membershipDuration ?: "").replaceFirst(Regex("^Member for\\s*", RegexOption.IGNORE_CASE), "")
    },
    Col("Friends", Kind.FRIENDS, 96.dp) { it.friendsCount?.toString() ?: (it.friends ?: "") },
    Col("Aaronic", Kind.YESNO, 96.dp) { it.aaronicPriesthood ?: "" },
    Col("Melch.", Kind.YESNO, 92.dp) { it.melchizedekPriesthood ?: "" },
    Col("Calling", Kind.YESNO, 96.dp) { it.calling ?: "" },
    Col("Has min.", Kind.YESNO, 100.dp) { it.ministeringBrothersSisters ?: "" },
    Col("Gives min.", Kind.YESNO, 106.dp) { it.ministeringAssignment ?: "" },
    Col("Recommend", Kind.RECOMMEND, 118.dp) { it.templeRecommend ?: "" },
    Col("Patriarchal", Kind.YESNO, 116.dp) { it.patriarchalBlessing ?: "" },
    Col("Endowed", Kind.YESNO, 102.dp) { it.livingOrdinance ?: "" },
    Col("1st temple visit", Kind.YESNO, 128.dp) { Milestones.firstTempleVisitDisplay(it) },
    Col("Family name", Kind.YESNO, 116.dp) { Milestones.familyNameDisplay(it) },
)
