package org.membercovenantpath.viewer.ui.components

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowForward
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.outlined.Circle
import androidx.compose.material3.Icon
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import org.membercovenantpath.viewer.logic.Milestone
import org.membercovenantpath.viewer.logic.Milestones
import org.membercovenantpath.viewer.model.Member
import org.membercovenantpath.viewer.ui.theme.StatusColors
import java.time.LocalDate

/**
 * Row of small circle chips for one member (filled = done). With [highlightNext], the first
 * not-yet-complete eligible milestone gets an amber ring as the suggested next step. [labeled]
 * renders full-text pills (person detail) instead of compact circles (lists).
 *
 * Ported from golden_hour.dart `GoldenHourChips`.
 */
@Composable
fun GoldenHourChips(
    member: Member,
    modifier: Modifier = Modifier,
    size: Dp = 24.dp,
    highlightNext: Boolean = false,
    labeled: Boolean = false,
    today: LocalDate = LocalDate.now(),
) {
    val list = Milestones.forMember(member, today)
    val nextIdx = if (highlightNext) list.indexOfFirst { !it.complete(member) } else -1

    FlowLayout(
        modifier = modifier,
        horizontalSpacing = if (labeled) 8.dp else 5.dp,
        verticalSpacing = if (labeled) 8.dp else 5.dp,
    ) {
        list.forEachIndexed { i, ms ->
            if (labeled) LabeledChip(ms, ms.complete(member), isNext = i == nextIdx)
            else CircleChip(ms, ms.complete(member), isNext = i == nextIdx, size = size)
        }
    }
}

@Composable
private fun LabeledChip(ms: Milestone, done: Boolean, isNext: Boolean) {
    val green = StatusColors.DoneGreen
    val amber = StatusColors.NextAmber
    val c = if (done) green else if (isNext) amber else StatusColors.GreyText
    val bg = when {
        done -> green.copy(alpha = 0.12f)
        isNext -> amber.copy(alpha = 0.12f)
        else -> Color.Transparent
    }
    Surface(
        color = bg,
        shape = RoundedCornerShape(20.dp),
        border = BorderStroke(if (isNext) 1.6.dp else 1.dp, c),
    ) {
        Row(
            verticalAlignment = Alignment.CenterVertically,
            modifier = Modifier.padding(horizontal = 10.dp, vertical = 5.dp),
        ) {
            Icon(
                imageVector = if (done) Icons.Filled.CheckCircle
                else if (isNext) Icons.Filled.ArrowForward else Icons.Outlined.Circle,
                contentDescription = null,
                tint = c,
                modifier = Modifier.size(15.dp),
            )
            Text(
                text = "  ${ms.label}",
                color = c,
                fontSize = 13.sp,
                fontWeight = FontWeight.Medium,
            )
        }
    }
}

@Composable
private fun CircleChip(ms: Milestone, done: Boolean, isNext: Boolean, size: Dp) {
    val green = StatusColors.DoneGreen
    val amber = StatusColors.NextAmber
    val border = if (done) green else if (isNext) amber else StatusColors.GreyBorder
    val fill = when {
        done -> green
        isNext -> amber.copy(alpha = 0.15f)
        else -> Color.Transparent
    }
    val textColor = if (done) Color.White else if (isNext) amber else StatusColors.GreyText
    Surface(
        color = fill,
        shape = CircleShape,
        border = BorderStroke(if (isNext) 2.dp else 1.2.dp, border),
        modifier = Modifier.size(size),
    ) {
        Box(contentAlignment = Alignment.Center) {
            Text(
                text = ms.abbr,
                color = textColor,
                fontWeight = FontWeight.Bold,
                fontSize = if (ms.abbr.length >= 2) 8.5.sp else 11.sp,
            )
        }
    }
}
