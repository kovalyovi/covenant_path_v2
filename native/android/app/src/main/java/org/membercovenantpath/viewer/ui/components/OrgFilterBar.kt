package org.membercovenantpath.viewer.ui.components

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.FilterAltOff
import androidx.compose.material3.AssistChip
import androidx.compose.material3.AssistChipDefaults
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import org.membercovenantpath.viewer.logic.OrgBucket
import org.membercovenantpath.viewer.logic.Orgs

/**
 * Org-ownership filter bar: a colored toggle chip per org (WML / EQ / RS), ALL selected by default.
 * Tapping toggles (multi-select; can't deselect the last). When not all three are on, a "Clear
 * filters" affordance restores them. Colors come from [Orgs.info] so they stay consistent with the
 * per-member responsibility chips. Ported from golden_hour_view.dart `_OrgFilterBar`.
 */
@Composable
fun OrgFilterBar(
    selected: Set<OrgBucket>,
    onToggle: (OrgBucket) -> Unit,
    onClear: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val all = selected.size == OrgBucket.entries.size
    FlowLayout(modifier = modifier, horizontalSpacing = 6.dp, verticalSpacing = 6.dp) {
        OrgBucket.entries.forEach { b ->
            val info = Orgs.info(b)
            val sel = b in selected
            FilterChip(
                selected = sel,
                onClick = { onToggle(b) },
                label = {
                    Text(
                        info.label,
                        color = if (sel) info.color else info.color.copy(alpha = 0.6f),
                        fontWeight = if (sel) FontWeight.Bold else FontWeight.Medium,
                    )
                },
                leadingIcon = {
                    Icon(info.icon, contentDescription = null, tint = info.color, modifier = Modifier.size(16.dp))
                },
                colors = FilterChipDefaults.filterChipColors(
                    containerColor = info.color.copy(alpha = 0.06f),
                    selectedContainerColor = info.color.copy(alpha = 0.22f),
                ),
                border = BorderStroke(1.dp, info.color.copy(alpha = if (sel) 0.9f else 0.35f)),
            )
        }
        if (!all) {
            AssistChip(
                onClick = onClear,
                label = { Text("Clear filters") },
                leadingIcon = {
                    Icon(Icons.Outlined.FilterAltOff, contentDescription = null, modifier = Modifier.size(16.dp))
                },
            )
        }
    }
}
