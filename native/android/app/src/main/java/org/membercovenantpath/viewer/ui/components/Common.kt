package org.membercovenantpath.viewer.ui.components

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/** Thin wrapper over the foundation [FlowRow] with explicit gaps (Wrap-like API). */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun FlowLayout(
    modifier: Modifier = Modifier,
    horizontalSpacing: Dp = 8.dp,
    verticalSpacing: Dp = 8.dp,
    content: @Composable () -> Unit,
) {
    FlowRow(
        modifier = modifier,
        horizontalArrangement = Arrangement.spacedBy(horizontalSpacing),
        verticalArrangement = Arrangement.spacedBy(verticalSpacing),
        content = { content() },
    )
}

/**
 * Titled section as a clean rounded, outlined card — the building block for detail/summary pages.
 * Ported from golden_hour.dart `SectionCard`.
 */
@Composable
fun SectionCard(
    title: String,
    modifier: Modifier = Modifier,
    leadingIcon: ImageVector? = null,
    iconColor: Color? = null,
    leadingContent: (@Composable () -> Unit)? = null,
    trailing: (@Composable () -> Unit)? = null,
    onClick: (() -> Unit)? = null,
    content: @Composable () -> Unit,
) {
    val accent = iconColor ?: MaterialTheme.colorScheme.primary
    val shape = RoundedCornerShape(16.dp)
    val base = Modifier
        .fillMaxWidth()
        .padding(vertical = 6.dp)
        .let { if (onClick != null) it.clip(shape).clickable(onClick = onClick) else it }
    Card(
        modifier = modifier.then(base),
        shape = shape,
        elevation = CardDefaults.cardElevation(0.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
    ) {
        Column(Modifier.padding(16.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                if (leadingContent != null) {
                    leadingContent()   // custom leading element (e.g. a completion ring) replaces the glyph
                    Spacer(Modifier.width(10.dp))
                } else if (leadingIcon != null) {
                    Surface(
                        color = accent.copy(alpha = 0.14f),
                        shape = RoundedCornerShape(10.dp),
                    ) {
                        Icon(
                            leadingIcon,
                            contentDescription = null,
                            tint = accent,
                            modifier = Modifier.padding(7.dp).size(18.dp),
                        )
                    }
                    Spacer(Modifier.width(10.dp))
                }
                Text(
                    title,
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Bold,
                    modifier = Modifier.weight(1f),
                )
                if (trailing != null) trailing()
            }
            Spacer(Modifier.size(12.dp))
            content()
        }
    }
}

/** Small pill count badge (golden_hour `_CountBadge`). */
@Composable
fun CountBadge(n: Int) {
    Surface(
        color = MaterialTheme.colorScheme.secondaryContainer,
        shape = RoundedCornerShape(20.dp),
    ) {
        Text(
            "$n",
            color = MaterialTheme.colorScheme.onSecondaryContainer,
            fontWeight = FontWeight.Bold,
            fontSize = 12.sp,
            modifier = Modifier.padding(horizontal = 9.dp, vertical = 2.dp),
        )
    }
}

/** A muted one-liner (used for empty-state notes). */
@Composable
fun MutedText(text: String, modifier: Modifier = Modifier) {
    Text(text, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = modifier)
}

/** A slim accent bar + bold title, the section header anchor (dashboard_common `_BigHeader`). */
@Composable
fun BigHeader(text: String, subtitle: String? = null, modifier: Modifier = Modifier) {
    Row(modifier = modifier, verticalAlignment = Alignment.Top) {
        AccentBar(height = if (subtitle != null) 34.dp else 22.dp)
        Spacer(Modifier.width(10.dp))
        Column {
            Text(text, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
            if (subtitle != null) {
                Text(
                    subtitle,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

/** The 4dp rounded accent bar used to anchor section headers. */
@Composable
fun AccentBar(height: Dp, color: Color = MaterialTheme.colorScheme.primary) {
    Box(
        Modifier
            .size(width = 4.dp, height = height)
            .clip(RoundedCornerShape(2.dp))
            .background(color)
    )
}
