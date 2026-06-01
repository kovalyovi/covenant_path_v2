package org.membercovenantpath.viewer.ui.components

import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
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
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

/**
 * Content-shaped skeletons (the native analog of widgets/shimmer.dart) so the dashboard renders its
 * layout immediately and swaps to data without a blank→content jump (PARITY #11). A subtle animated
 * gradient sweeps across the placeholder blocks.
 */
@Composable
private fun shimmerBrush(): Brush {
    val transition = rememberInfiniteTransition(label = "shimmer")
    val x by transition.animateFloat(
        initialValue = 0f,
        targetValue = 1000f,
        animationSpec = infiniteRepeatable(tween(1100), RepeatMode.Restart),
        label = "x",
    )
    val base = MaterialTheme.colorScheme.surfaceVariant
    val hi = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.4f)
    return Brush.linearGradient(
        colors = listOf(base, hi, base),
        start = androidx.compose.ui.geometry.Offset(x - 300f, 0f),
        end = androidx.compose.ui.geometry.Offset(x, 0f),
    )
}

@Composable
fun ShimmerBlock(width: Dp, height: Dp, modifier: Modifier = Modifier) {
    Box(
        modifier
            .size(width = width, height = height)
            .clip(RoundedCornerShape(6.dp))
            .background(shimmerBrush()),
    )
}

@Composable
private fun ShimmerLine(fraction: Float, height: Dp = 12.dp) {
    Box(
        Modifier
            .fillMaxWidth(fraction)
            .height(height)
            .clip(RoundedCornerShape(6.dp))
            .background(shimmerBrush()),
    )
}

/** A list of member-row-shaped skeletons — the dashboard's loading state. */
@Composable
fun MemberListSkeleton(rows: Int = 8) {
    LazyColumn(
        Modifier.fillMaxWidth(),
        contentPadding = androidx.compose.foundation.layout.PaddingValues(14.dp),
    ) {
        items((0 until rows).toList()) {
            Row(Modifier.fillMaxWidth().padding(vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.size(44.dp).clip(CircleShape).background(shimmerBrush()))
                Spacer(Modifier.width(12.dp))
                Column {
                    ShimmerLine(0.55f, 14.dp)
                    Spacer(Modifier.height(8.dp))
                    ShimmerLine(0.38f, 11.dp)
                }
            }
        }
    }
}

/** A small card-shaped skeleton for sheets/panels (sync settings, admin sections). */
@Composable
fun CardSkeleton(lines: Int = 3, modifier: Modifier = Modifier) {
    Column(modifier.fillMaxWidth().padding(vertical = 8.dp)) {
        repeat(lines) { i ->
            ShimmerLine(if (i == 0) 0.7f else 0.9f - i * 0.08f)
            Spacer(Modifier.height(10.dp))
        }
    }
}
