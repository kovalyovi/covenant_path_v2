package org.membercovenantpath.viewer.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import org.membercovenantpath.viewer.data.ThemeChoice

/**
 * Material 3 theme, indigo-seeded to match the Flutter app (ColorScheme.fromSeed(Colors.indigo)) so
 * the two builds read identically. Honors a persisted light/dark/system [choice]. Dynamic color is
 * intentionally OFF — the brand indigo + the deliberate tab/org/milestone accents must stay constant
 * across devices (and match the web build), which Android's wallpaper-derived palette would override.
 */

private val LightScheme = lightColorScheme(
    primary = Indigo,
    primaryContainer = Color(0xFFC5CAE9),
    onPrimaryContainer = Color(0xFF1A237E),
    secondaryContainer = Color(0xFFE8EAF6),
)

private val DarkScheme = darkColorScheme(
    primary = Color(0xFF9FA8DA),
    primaryContainer = Color(0xFF283593),
    onPrimaryContainer = Color(0xFFE8EAF6),
)

@Composable
fun CovenantPathTheme(
    choice: ThemeChoice = ThemeChoice.System,
    content: @Composable () -> Unit,
) {
    val darkTheme = when (choice) {
        ThemeChoice.System -> isSystemInDarkTheme()
        ThemeChoice.Light -> false
        ThemeChoice.Dark -> true
    }
    val colorScheme = if (darkTheme) DarkScheme else LightScheme

    MaterialTheme(
        colorScheme = colorScheme,
        typography = Typography(),
        shapes = MaterialTheme.shapes.copy(medium = RoundedCornerShape(12.dp)),
        content = content,
    )
}
