package org.membercovenantpath.viewer.logic

import org.membercovenantpath.viewer.data.BrokerFactor

/**
 * Source-naming copy for the MFA code step (2026-06-11): with several methods enrolled, the
 * common failure is a right-looking code from the WRONG source — an authenticator-app code typed
 * into a text challenge, or an earlier text's code. The prompt names exactly which code belongs
 * in the box (the label is Okta's own masked destination, e.g. "+1 XXX-XX34"), the warning heads
 * off the authenticator mix-up, and the no-code hint surfaces the stale-number escape hatch.
 * Mirrors web `mfaCopy.ts` and Swift `MfaCopy.swift` — change all three together.
 */
data class MfaPrompt(val prompt: String, val warning: String? = null, val noCodeHint: String? = null)

fun mfaPrompt(f: BrokerFactor): MfaPrompt {
    val method = f.method.lowercase()
    // Shape B's generic placeholder — we don't know the factor, keep the generic copy.
    if (f.id == "pending") {
        return MfaPrompt("A code was just sent via ${f.label}. Wait for the new one to arrive, then enter it here.")
    }
    return when (method) {
        "sms", "voice" -> {
            val channel = if (method == "voice") "call" else "text"
            MfaPrompt(
                prompt = "A new code was just sent via ${f.label}. Enter the 6-digit code from that newest $channel.",
                warning = "Don't enter a code from an authenticator app or an older text here.",
                noCodeHint = "No $channel after 30 seconds? The number on file may be out of date — " +
                    "update it at churchofjesuschrist.org, or choose a different method.",
            )
        }
        "email" -> MfaPrompt(
            "A new code was just sent via ${f.label}. Enter the code from the newest email — it can take a minute to arrive.",
        )
        "otp", "totp" -> MfaPrompt("Enter the current code shown in ${f.label}.")
        // Passwordless-lane MFA continuation: the emailed code was ACCEPTED and Okta now wants a
        // DISTINCT factor type — for Church accounts that's the password (2026-06-12).
        "password" -> MfaPrompt(
            "Your code was accepted. Your account uses multi-factor sign-in, so enter your " +
                "Church Account password to finish.",
        )
        else -> MfaPrompt("A code was just sent via ${f.label}. Wait for the new one to arrive, then enter it here.")
    }
}

// NOTE: otpUsernameHint() was removed 2026-06-12 with the passwordless Church-OTP lane (it couldn't
// mint the daily-sync token). Church sign-in is username+password only. See docs/DECISIONS.md ADR-010.
