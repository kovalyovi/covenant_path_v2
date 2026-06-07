package org.membercovenantpath.viewer.ui.components

import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.HorizontalDivider
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

/** #16: small placeholder for the sync-settings schedule / Drive sub-sections while their broker
 *  calls resolve — so they fade in as a skeleton instead of abruptly appearing once loaded. */
@Composable
fun SyncSubsectionSkeleton() {
    Column(Modifier.fillMaxWidth()) {
        HorizontalDivider(Modifier.padding(vertical = 16.dp))
        CardSkeleton(lines = 2)
    }
}

// ---- N8 content-shaped tab skeletons ----------------------------------------

/** A full-width shimmer block (e.g. the chart area), unlike the fixed-size [ShimmerBlock]. */
@Composable
private fun ShimmerFill(height: Dp, radius: Dp = 12.dp) {
    Box(Modifier.fillMaxWidth().height(height).clip(RoundedCornerShape(radius)).background(shimmerBrush()))
}

/** A bordered rounded card shaped exactly like [SectionCard] (radius 16, surface, outlineVariant
 * border, padding 16) so KPI/Golden-Hour skeletons occupy the real card footprint — no layout jump. */
@Composable
private fun SkelCard(content: @Composable ColumnScope.() -> Unit) {
    Card(
        modifier = Modifier.fillMaxWidth().padding(vertical = 6.dp),
        shape = RoundedCornerShape(16.dp),
        elevation = CardDefaults.cardElevation(0.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
    ) {
        Column(Modifier.padding(16.dp), content = content)
    }
}

/** One member-row placeholder (avatar + two lines + trailing chip) — shared by the GH grid skeleton. */
@Composable
private fun SkelMemberRow() {
    Row(Modifier.fillMaxWidth().padding(vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.size(44.dp).clip(CircleShape).background(shimmerBrush()))
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            ShimmerLine(0.55f, 14.dp)
            Spacer(Modifier.height(8.dp))
            ShimmerLine(0.38f, 11.dp)
        }
        Spacer(Modifier.width(12.dp))
        ShimmerBlock(52.dp, 22.dp)
    }
}

/** One Golden-Hour completion stat: big % + label + progress bar — matches `pctStat` (width 124). */
@Composable
private fun SkelPctStat() {
    Column(Modifier.width(124.dp)) {
        ShimmerBlock(54.dp, 22.dp)
        Spacer(Modifier.height(8.dp))
        ShimmerBlock(100.dp, 11.dp)
        Spacer(Modifier.height(8.dp))
        ShimmerBlock(110.dp, 5.dp)
    }
}

/**
 * N8: content-shaped skeleton for the Golden Hour tab — the section toggle, org filter chips and
 * window selector, the "Golden Hour completion" card (a flow of % stats), then the per-unit member
 * grid. Mirrors GoldenHourScreen so nothing shifts when the data lands.
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun GoldenHourSkeleton() {
    Column(Modifier.fillMaxWidth().verticalScroll(rememberScrollState()).padding(14.dp)) {
        ShimmerBlock(300.dp, 38.dp, Modifier.align(Alignment.CenterHorizontally))      // section toggle
        Spacer(Modifier.height(12.dp))
        Row(Modifier.align(Alignment.CenterHorizontally), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            repeat(3) { ShimmerBlock(if (it == 0) 64.dp else 56.dp, 32.dp) }            // org filter chips
        }
        Spacer(Modifier.height(12.dp))
        ShimmerBlock(260.dp, 36.dp, Modifier.align(Alignment.CenterHorizontally))      // window selector
        Spacer(Modifier.height(12.dp))
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {  // section title
            ShimmerBlock(170.dp, 20.dp)
            ShimmerBlock(120.dp, 30.dp)
        }
        Spacer(Modifier.height(8.dp))
        SkelCard {                                                                     // completion card
            ShimmerBlock(190.dp, 16.dp)
            Spacer(Modifier.height(16.dp))
            FlowRow(horizontalArrangement = Arrangement.spacedBy(18.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                repeat(6) { SkelPctStat() }
            }
        }
        Spacer(Modifier.height(12.dp))
        repeat(2) {                                                                    // per-unit grid
            ShimmerBlock(140.dp, 16.dp)
            Spacer(Modifier.height(10.dp))
            repeat(3) { SkelMemberRow() }
            Spacer(Modifier.height(12.dp))
        }
    }
}

/** Two stacked label/number blocks — matches the KPI cards' big-stat pair. */
@Composable
private fun SkelStat(modifier: Modifier = Modifier) {
    Column(modifier) {
        ShimmerBlock(70.dp, 11.dp)
        Spacer(Modifier.height(6.dp))
        ShimmerBlock(50.dp, 24.dp)
    }
}

/** One "Overview" stat (width 124): big number + label — matches `OverviewCard`'s cells. */
@Composable
private fun SkelOverviewStat() {
    Column(Modifier.width(124.dp)) {
        ShimmerBlock(46.dp, 26.dp)
        Spacer(Modifier.height(8.dp))
        ShimmerBlock(100.dp, 11.dp)
    }
}

/** A KPI chart card placeholder: icon + title, an optional window selector (Baptisms), the two big
 * stats, the 170-dp chart area, and a caption — shaped like `BaptismsCard`/`MetricChartCard`. */
@Composable
private fun SkelChartCard(withWindow: Boolean) {
    SkelCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            ShimmerBlock(32.dp, 32.dp)
            Spacer(Modifier.width(10.dp))
            ShimmerBlock(150.dp, 18.dp)
        }
        Spacer(Modifier.height(14.dp))
        if (withWindow) {
            ShimmerBlock(260.dp, 34.dp, Modifier.align(Alignment.CenterHorizontally))
            Spacer(Modifier.height(14.dp))
        }
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(28.dp)) {
            SkelStat(Modifier.weight(1f))
            SkelStat(Modifier.weight(1f))
        }
        Spacer(Modifier.height(16.dp))
        ShimmerFill(170.dp)
        Spacer(Modifier.height(12.dp))
        ShimmerLine(0.7f, 11.dp)
    }
}

/**
 * N8: content-shaped skeleton for the KPIs tab — the big header + period selector, two chart cards
 * (the first carrying the Baptisms window selector) and the Overview stat grid. Mirrors KpisScreen.
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun KpiSkeleton() {
    Column(Modifier.fillMaxWidth().verticalScroll(rememberScrollState()).padding(14.dp)) {
        Row(Modifier.fillMaxWidth()) {                                                 // big header
            ShimmerBlock(4.dp, 34.dp)
            Spacer(Modifier.width(10.dp))
            Column(Modifier.weight(1f)) {
                ShimmerBlock(90.dp, 24.dp)
                Spacer(Modifier.height(8.dp))
                ShimmerLine(0.65f, 12.dp)
            }
        }
        Spacer(Modifier.height(14.dp))
        ShimmerBlock(220.dp, 36.dp, Modifier.align(Alignment.CenterHorizontally))      // period selector
        Spacer(Modifier.height(14.dp))
        SkelChartCard(withWindow = true)                                               // Baptisms
        SkelChartCard(withWindow = false)                                              // a metric chart
        SkelCard {                                                                     // Overview grid
            ShimmerBlock(110.dp, 18.dp)
            Spacer(Modifier.height(16.dp))
            FlowRow(horizontalArrangement = Arrangement.spacedBy(24.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
                repeat(4) { SkelOverviewStat() }
            }
        }
    }
}
