package org.membercovenantpath.viewer.ui.screens

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp

/** Shown when SUPABASE_URL / SUPABASE_ANON_KEY are blank (mirrors Flutter `_ConfigError`). */
@Composable
fun ConfigErrorScreen() {
    Box(Modifier.fillMaxSize().padding(24.dp), contentAlignment = Alignment.Center) {
        Text(
            "Missing SUPABASE_URL / SUPABASE_ANON_KEY.\n\n" +
                "Build with:\n" +
                "./gradlew assembleDebug \\\n" +
                "  -PSUPABASE_URL=https://<ref>.supabase.co \\\n" +
                "  -PSUPABASE_ANON_KEY=sb_publishable_...\n\n" +
                "(or set them as environment variables / in ~/.gradle/gradle.properties)",
            textAlign = TextAlign.Center,
            style = MaterialTheme.typography.bodyMedium,
        )
    }
}
