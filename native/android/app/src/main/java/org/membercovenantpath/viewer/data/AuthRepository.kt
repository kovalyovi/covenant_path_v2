package org.membercovenantpath.viewer.data

import io.github.jan.supabase.SupabaseClient
import io.github.jan.supabase.auth.OtpType
import io.github.jan.supabase.auth.auth
import io.github.jan.supabase.auth.providers.builtin.OTP
import io.github.jan.supabase.auth.status.SessionStatus
import kotlinx.coroutines.flow.Flow

/**
 * Email-OTP auth, mirroring the Flutter login flow (login_page.dart `_sendEmailCode` /
 * `_verifyEmailCode`) using supabase-kt's gotrue (`auth-kt`) module:
 *   1. [sendEmailCode]  → signInWith(OTP) { email = ... }  (Supabase emails a 6-digit code)
 *   2. [verifyEmailCode] → verifyEmailOtp(type = EMAIL, email, token)  → a live session
 *
 * RLS then scopes every query by the verified email. (Church-account broker + passkeys are out of
 * scope for the PoC, per SPEC.md.)
 */
class AuthRepository(
    private val client: SupabaseClient = SupabaseClientProvider.client,
) {
    /** Emits the current auth session status; the app routes Login vs Dashboard off this. */
    val sessionStatus: Flow<SessionStatus> get() = client.auth.sessionStatus

    val isAuthenticated: Boolean
        get() = client.auth.currentSessionOrNull() != null

    val currentEmail: String?
        get() = client.auth.currentUserOrNull()?.email

    /** The signed-in user's Supabase access token (Bearer for broker/admin calls), or null. */
    val accessToken: String?
        get() = client.auth.currentAccessTokenOrNull()

    /** Send a 6-digit email OTP. `createUser = true` so power-user invitees without an account work. */
    suspend fun sendEmailCode(email: String) {
        client.auth.signInWith(OTP) {
            this.email = email.trim()
            this.createUser = true
        }
    }

    /** Verify the emailed code; on success a session is established (sessionStatus emits Authenticated). */
    suspend fun verifyEmailCode(email: String, token: String) {
        client.auth.verifyEmailOtp(
            type = OtpType.Email.EMAIL,
            email = email.trim(),
            token = token.trim(),
        )
    }

    /**
     * Adopt a broker-minted OTP as a real Supabase session — the Church-account + passkey flows: the
     * broker authenticates server-side and returns {email, otp}, which is a verifiable email OTP.
     * Mirrors login_page.dart `_consume`.
     */
    suspend fun verifyBrokerOtp(email: String, otp: String) {
        client.auth.verifyEmailOtp(type = OtpType.Email.EMAIL, email = email.trim(), token = otp.trim())
    }

    /**
     * Adopt a session from a refresh token (the email-relay backup: the broker verifies the code
     * server-side and returns {access_token, refresh_token}). Mirrors `setSession(refresh_token)`.
     */
    suspend fun adoptRefreshToken(refreshToken: String) {
        val session = client.auth.refreshSession(refreshToken)
        client.auth.importSession(session)
    }

    suspend fun signOut() {
        client.auth.signOut()
    }
}
