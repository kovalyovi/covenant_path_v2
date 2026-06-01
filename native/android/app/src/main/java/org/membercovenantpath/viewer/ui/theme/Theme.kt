package org.membercovenantpath.viewer.ui.theme

import android.app.Activity
import android.os.Build
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.dynamicDarkColorScheme
import androidx.compose.material3.dynamicLightColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext

/**
 * Material 3 theme. Indigo-seeded to match the Flutter app (ColorScheme.fromSeed(Colors.indigo)).
 * Honors system light/dark. Opts into Android 12+ dynamic color when available — a native nicety
 * the Flutter web app can't do — falling back to indigo-derived static schemes otherwise.
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
    darkTheme: Boolean = isSystemInDarkTheme(),
    dynamicColor: Boolean = true,
    content: @Composable () -> Unit,
) {
    val context = LocalContext.current
    val colorScheme = when {
        dynamicColor && Build.VERSION.SDK_INT >= Build.VERSION_CODES.S ->
            if (darkTheme) dynamicDarkColorScheme(context) else dynamicLightColorScheme(context)
        darkTheme -> DarkScheme
        else -> LightScheme
    }

    MaterialTheme(
        colorScheme = colorScheme,
        typography = Typography(),
        content = content,
    )
}
