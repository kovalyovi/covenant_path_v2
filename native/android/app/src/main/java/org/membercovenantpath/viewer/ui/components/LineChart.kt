package org.membercovenantpath.viewer.ui.components

import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.drawText
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlin.math.max
import kotlin.math.roundToInt

/**
 * iOS-style trend line, hand-drawn on a Compose Canvas (no chart-lib dependency → nothing to break
 * the CI build). Smooth-ish curve, gradient fill, white-cored dots, an always-on value label above
 * each point, sparse gray x-axis labels, and an optional dashed previous-period overlay. Tapping a
 * point reports its bucket index. Mirrors kpis_view.dart `_Line` behavior.
 */
@Composable
fun LineChart(
    values: List<Double>,
    labels: List<String>,
    color: Color,
    prev: List<Double> = emptyList(),
    modifier: Modifier = Modifier,
    onBucketTap: ((Int) -> Unit)? = null,
) {
    if (values.isEmpty()) {
        Box(modifier.fillMaxWidth().height(170.dp), contentAlignment = Alignment.Center) {
            Text("No data yet", color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        return
    }
    val measurer = rememberTextMeasurer()
    val density = LocalDensity.current
    val axisColor = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.6f)
    val prevColor = MaterialTheme.colorScheme.outline

    val peak = (values + prev).maxOrNull() ?: 0.0
    val maxY = peak * 1.35 + 1.0 // headroom so labels above points aren't clipped
    val step = max(1, Math.ceil(values.size / 3.0).toInt())

    Box(
        modifier
            .fillMaxWidth()
            .height(170.dp)
            .then(
                if (onBucketTap == null) Modifier
                else Modifier.pointerInput(values, labels) {
                    detectTapGestures { pos ->
                        // map x → nearest bucket index over the same inset the chart uses
                        val leftPad = with(density) { 6.dp.toPx() }
                        val rightPad = with(density) { 6.dp.toPx() }
                        val w = size.width - leftPad - rightPad
                        if (values.size <= 1) { onBucketTap(0); return@detectTapGestures }
                        val rel = ((pos.x - leftPad) / w).coerceIn(0f, 1f)
                        val idx = (rel * (values.size - 1)).roundToInt().coerceIn(0, values.size - 1)
                        onBucketTap(idx)
                    }
                },
            ),
    ) {
        androidx.compose.foundation.Canvas(Modifier.fillMaxSize()) {
            val leftPad = 6.dp.toPx()
            val rightPad = 6.dp.toPx()
            val topPad = 18.dp.toPx() // room for value labels
            val bottomPad = 22.dp.toPx() // room for x labels
            val w = size.width - leftPad - rightPad
            val h = size.height - topPad - bottomPad

            fun x(i: Int): Float = if (values.size <= 1) leftPad + w / 2 else leftPad + w * i / (values.size - 1)
            fun y(v: Double): Float = topPad + (h - (v / maxY * h).toFloat()).coerceIn(0f, h)

            // previous-period overlay (dashed, faded) drawn first so the current line sits on top
            if (prev.isNotEmpty() && prev.size == values.size) {
                val p = Path()
                prev.forEachIndexed { i, v -> if (i == 0) p.moveTo(x(i), y(v)) else p.lineTo(x(i), y(v)) }
                drawPath(
                    p, color = prevColor, style = Stroke(width = 2.dp.toPx(),
                        pathEffect = PathEffect.dashPathEffect(floatArrayOf(5.dp.toPx(), 4.dp.toPx()))),
                )
            }

            // gradient fill under the current line
            val fill = Path().apply {
                moveTo(x(0), topPad + h)
                values.forEachIndexed { i, v -> lineTo(x(i), y(v)) }
                lineTo(x(values.size - 1), topPad + h)
                close()
            }
            drawPath(
                fill,
                brush = androidx.compose.ui.graphics.Brush.verticalGradient(
                    colors = listOf(color.copy(alpha = 0.28f), color.copy(alpha = 0.02f)),
                    startY = topPad, endY = topPad + h,
                ),
            )

            // the line
            val line = Path()
            values.forEachIndexed { i, v -> if (i == 0) line.moveTo(x(i), y(v)) else line.lineTo(x(i), y(v)) }
            drawPath(line, color = color, style = Stroke(width = 3.dp.toPx()))

            // dots (white core + colored ring) + value label above each
            values.forEachIndexed { i, v ->
                val cx = x(i); val cy = y(v)
                drawCircle(color = Color.White, radius = 3.5.dp.toPx(), center = Offset(cx, cy))
                drawCircle(color = color, radius = 3.5.dp.toPx(), center = Offset(cx, cy), style = Stroke(width = 2.dp.toPx()))
                val label = if (v == v.roundToInt().toDouble()) "${v.roundToInt()}" else "%.0f".format(v)
                val tl = measurer.measure(label, TextStyle(color = color, fontSize = 11.sp))
                drawText(tl, topLeft = Offset(cx - tl.size.width / 2, cy - tl.size.height - 4.dp.toPx()))
            }

            // sparse x-axis labels (every `step`, plus the last)
            labels.forEachIndexed { i, lbl ->
                if (i % step != 0 && i != labels.size - 1) return@forEachIndexed
                val tl = measurer.measure(lbl, TextStyle(color = axisColor, fontSize = 10.sp))
                val cx = (x(i) - tl.size.width / 2).coerceIn(0f, size.width - tl.size.width)
                drawText(tl, topLeft = Offset(cx, topPad + h + 6.dp.toPx()))
            }
        }
    }
}
