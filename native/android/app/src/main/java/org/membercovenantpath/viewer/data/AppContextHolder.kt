package org.membercovenantpath.viewer.data

import android.content.Context

/**
 * Holds the application Context for components that need one but live outside an Activity
 * (e.g. [EncryptedSessionManager]). Set once in MainActivity.onCreate BEFORE any Supabase access.
 * Reads guard with [isReady] so a not-yet-initialized access degrades gracefully (the Supabase
 * client wiring falls back to the default session manager rather than crashing).
 */
object AppContextHolder {
    lateinit var context: Context
    val isReady: Boolean get() = ::context.isInitialized
}
