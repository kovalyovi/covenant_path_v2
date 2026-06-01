package org.membercovenantpath.viewer

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import org.membercovenantpath.viewer.ui.App

/**
 * Single-Activity host. All UI is Compose ([App]); navigation is navigation-compose. Edge-to-edge
 * for a modern look (the Scaffolds consume the insets via their content padding).
 */
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)
        setContent { App() }
    }
}
