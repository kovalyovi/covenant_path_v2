package org.membercovenantpath.viewer.ui.screens.tabs

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowDownward
import androidx.compose.material.icons.filled.ArrowUpward
import androidx.compose.material.icons.filled.UnfoldMore
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import org.membercovenantpath.viewer.model.Member
import org.membercovenantpath.viewer.ui.theme.StatusColors

/**
 * Every covenant-path field in a sortable, color-coded grid (Yes=green / No=red / N/A=grey,
 * recommend Active/Expired/No, sex M/F). 3-state sort on text columns. Ported from
 * table_view.dart `_SpreadsheetView` (filter popups omitted for the PoC; sorting kept).
 */
@Composable
fun TableScreen(members: List<Member>, onOpen: (Member) -> Unit) {
    var sortCol by remember { mutableStateOf<Int?>(null) }
    var sortAsc by remember { mutableStateOf(true) }

    val rows = members.filterNot { it.isInvestigator }.let { list ->
        val col = sortCol ?: return@let list
        val key = Columns[col]
        list.sortedWith(compareBy(String.CASE_INSENSITIVE_ORDER) { key.value(it) })
            .let { if (sortAsc) it else it.reversed() }
    }

    fun onSort(col: Int) {
        if (sortCol == col) {
            if (sortAsc) sortAsc = false else sortCol = null
        } else { sortCol = col; sortAsc = true }
    }

    val hScroll = rememberScrollState()
    Column(Modifier.fillMaxWidth()) {
        Text(
            "${rows.size} member${if (rows.size == 1) "" else "s"}",
            style = MaterialTheme.typography.bodySmall,
            modifier = Modifier.padding(start = 12.dp, top = 8.dp, bottom = 4.dp),
        )
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
                )
            }
        }
        LazyColumn(Modifier.fillMaxWidth()) {
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
                    Columns.forEach { c -> ValueCell(c.value(m), c.kind, c.width) }
                }
            }
        }
    }
}

private val NumWidth = 36.dp

@Composable
private fun HeaderCell(label: String, width: Dp, sortable: Boolean, sortState: Int, onSort: () -> Unit) {
    Row(
        modifier = Modifier.width(width).padding(horizontal = 7.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(label, color = MaterialTheme.colorScheme.onPrimary, fontWeight = FontWeight.Bold, fontSize = 13.sp, maxLines = 1)
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
private fun ValueCell(value: String, kind: Kind, width: Dp) {
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
    Kind.TEXT -> null
}

private enum class Kind { TEXT, YESNO, RECOMMEND, GENDER }

private data class Col(val header: String, val kind: Kind, val width: Dp, val value: (Member) -> String)

/** Column set mirroring table_view.dart `_cols`. */
private val Columns: List<Col> = listOf(
    Col("Member", Kind.TEXT, 150.dp) { it.name ?: "" },
    Col("Sex", Kind.GENDER, 50.dp) { it.sex ?: "" },
    Col("Unit", Kind.TEXT, 130.dp) { it.unitName ?: "" },
    Col("Baptism", Kind.TEXT, 100.dp) { it.baptismDate ?: "" },
    Col("Member for", Kind.TEXT, 120.dp) {
        (it.membershipDuration ?: "").replaceFirst(Regex("^Member for\\s*", RegexOption.IGNORE_CASE), "")
    },
    Col("Friends", Kind.YESNO, 80.dp) { it.friends ?: "" },
    Col("Aaronic", Kind.YESNO, 80.dp) { it.aaronicPriesthood ?: "" },
    Col("Melch.", Kind.YESNO, 80.dp) { it.melchizedekPriesthood ?: "" },
    Col("Calling", Kind.YESNO, 80.dp) { it.calling ?: "" },
    Col("Has min.", Kind.YESNO, 80.dp) { it.ministeringBrothersSisters ?: "" },
    Col("Gives min.", Kind.YESNO, 90.dp) { it.ministeringAssignment ?: "" },
    Col("Recommend", Kind.RECOMMEND, 100.dp) { it.templeRecommend ?: "" },
    Col("Patriarchal", Kind.YESNO, 100.dp) { it.patriarchalBlessing ?: "" },
    Col("Endowed", Kind.YESNO, 90.dp) { it.livingOrdinance ?: "" },
)
