package org.membercovenantpath.viewer.ui

import androidx.biometric.BiometricManager
import androidx.biometric.BiometricPrompt
import androidx.core.content.ContextCompat
import androidx.fragment.app.FragmentActivity
import kotlin.coroutines.resume
import kotlinx.coroutines.suspendCancellableCoroutine

/**
 * Device-biometric app lock — fingerprint / face / device credential — the native analog of
 * biometric_gate.dart. Guards a restored session so a returning leader unlocks with biometrics
 * instead of re-authenticating; it never stores or replays a password. Uses androidx.biometric's
 * BiometricPrompt (needs a FragmentActivity, which MainActivity is).
 */
object AppBiometric {

    private const val AUTHENTICATORS =
        BiometricManager.Authenticators.BIOMETRIC_STRONG or BiometricManager.Authenticators.DEVICE_CREDENTIAL

    /** Whether this device can do biometrics (or a device credential fallback). */
    fun available(activity: FragmentActivity): Boolean =
        BiometricManager.from(activity).canAuthenticate(AUTHENTICATORS) == BiometricManager.BIOMETRIC_SUCCESS

    /** Show the system prompt; resolves true on success, false on cancel/error (stay locked). */
    suspend fun authenticate(activity: FragmentActivity): Boolean = suspendCancellableCoroutine { cont ->
        val executor = ContextCompat.getMainExecutor(activity)
        val prompt = BiometricPrompt(
            activity, executor,
            object : BiometricPrompt.AuthenticationCallback() {
                override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) {
                    if (cont.isActive) cont.resume(true)
                }
                override fun onAuthenticationError(errorCode: Int, errString: CharSequence) {
                    if (cont.isActive) cont.resume(false)
                }
                // onAuthenticationFailed (a single bad scan) is non-terminal; let the user retry.
            },
        )
        val info = BiometricPrompt.PromptInfo.Builder()
            .setTitle("Unlock Covenant Path")
            .setAllowedAuthenticators(AUTHENTICATORS)
            .build()
        runCatching { prompt.authenticate(info) }.onFailure { if (cont.isActive) cont.resume(false) }
    }
}
