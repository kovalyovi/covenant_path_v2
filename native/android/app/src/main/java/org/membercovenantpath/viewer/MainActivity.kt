package org.membercovenantpath.viewer

import android.os.Bundle
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.fragment.app.FragmentActivity
import org.membercovenantpath.viewer.data.AppContextHolder
import org.membercovenantpath.viewer.data.ErrorReporter
import org.membercovenantpath.viewer.ui.App

/**
 * Single-Activity host. All UI is Compose ([App]); navigation is navigation-compose. A
 * [FragmentActivity] so androidx.biometric's BiometricPrompt (the app-lock gate) can attach.
 * Edge-to-edge for a modern look; the Scaffolds consume the insets via their content padding.
 */
class MainActivity : FragmentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)
        // CLIENT-01: make the app Context available before any Supabase client access so the session
        // is persisted via the Keystore-backed EncryptedSessionManager.
        AppContextHolder.context = applicationContext
        ErrorReporter.install() // report uncaught errors to the broker /log (no PII)
        setContent { App() }
    }
}
