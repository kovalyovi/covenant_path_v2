package org.membercovenantpath.viewer.ui.components

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import org.membercovenantpath.viewer.data.AuthRepository
import org.membercovenantpath.viewer.data.BrokerClient
import org.membercovenantpath.viewer.data.BrokerException
import org.membercovenantpath.viewer.data.BrokerFactor
import org.membercovenantpath.viewer.data.BrokerResult

// N2: shown when the Church login succeeds but the calling has no covenant-path access.
private const val NO_ACCESS_MSG =
    "This account doesn't have access to Covenant Path. Access is granted by your calling — " +
        "if you should have access, ask your stake leadership."

/**
 * In-app Church re-authorization (port of web `ReauthDialog` — feedback: "hit re-authorize and was
 * pushed back to the login screen — should be an extra modal"). Opens over the dashboard, runs the
 * Church sign-in WITH sync consent (enroll=true, MFA-aware: factor pick + code, single-factor
 * auto-select), and keeps the user in the app: on success the broker stores the fresh credential,
 * we adopt the re-minted Supabase session (same user — never the login screen) and [onSuccess]
 * toasts + reloads enrollment status. Used by the stale/revoked banner and the empty-state CTAs.
 */
@Composable
fun ReauthDialog(onDismiss: () -> Unit, onSuccess: (String) -> Unit) {
    val broker = remember { BrokerClient() }
    val authRepo = remember { AuthRepository() }
    val scope = rememberCoroutineScope()

    var username by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    var mfaCode by remember { mutableStateOf("") }
    var loginId by remember { mutableStateOf<String?>(null) }
    var factors by remember { mutableStateOf<List<BrokerFactor>>(emptyList()) }
    var factorSent by remember { mutableStateOf<BrokerFactor?>(null) }
    var busy by remember { mutableStateOf(false) }
    var status by remember { mutableStateOf<String?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    // Same MFA-input hygiene as LoginScreen (2026-06-11): codes never survive a factor switch or
    // a failed verify, and resend cools down so the member waits for the FRESH code.
    var resendIn by remember { mutableStateOf(0) }
    LaunchedEffect(factorSent, resendIn > 0) {
        while (resendIn > 0) {
            delay(1_000)
            resendIn -= 1
        }
    }

    // The broker's access evaluation runs server-side on enroll (legitimately 30–60s) — surface the
    // web's progress note after 5s of busy.
    LaunchedEffect(busy) {
        status = null
        if (busy) {
            delay(5000)
            status = "Authorizing — checking what your calling can access (up to a minute)…"
        }
    }

    fun step(block: suspend () -> Unit) {
        scope.launch {
            busy = true
            error = null
            try {
                block()
            } catch (e: Throwable) {
                error = e.message ?: e.toString()
            }
            busy = false
        }
    }

    suspend fun finish(r: BrokerResult) {
        if (r.authorized == false) throw BrokerException(NO_ACCESS_MSG)
        // Adopt the freshly-minted session (same user — keeps them signed in, never the login screen).
        val email = r.email
        val otp = r.otp
        if (email != null && otp != null) authRepo.verifyBrokerOtp(email, otp)
        onSuccess(
            if (r.stored) "Daily sync authorized — your stake will refresh within minutes."
            else "Signed in — sync authorization completed.",
        )
    }

    fun signIn() = step {
        // enroll=true: this IS the consent (the whole point of re-authorizing).
        val r = broker.password(username.trim(), password, enroll = true)
        if (r.mfaRequired) {
            loginId = r.loginId
            factors = r.factors
            // Auto-send if there's exactly one factor (matches the login flow + web).
            if (r.factors.size == 1) {
                broker.selectFactor(r.loginId!!, r.factors.first().id)
                factorSent = r.factors.first()
                mfaCode = ""
                resendIn = 30
            }
            return@step
        }
        finish(r)
    }

    fun pickFactor(f: BrokerFactor) = step {
        broker.selectFactor(loginId!!, f.id)
        // Fresh challenge → fresh input; the cooldown nudges waiting for the NEW code.
        factorSent = f
        mfaCode = ""
        resendIn = 30
    }

    fun verify() = step {
        try {
            val r = broker.verifyMfa(loginId!!, mfaCode.trim(), enroll = true)
            finish(r)
        } catch (e: Throwable) {
            mfaCode = "" // a rejected code must be retyped fresh
            throw e
        }
    }

    AlertDialog(
        onDismissRequest = { if (!busy) onDismiss() },
        title = { Text("Re-authorize daily sync") },
        text = {
            Column {
                when {
                    factorSent != null -> {
                        Text("A code was just sent via ${factorSent?.label}. Wait for the new one to arrive, then enter it here.")
                        Spacer(Modifier.size(8.dp))
                        OutlinedTextField(
                            mfaCode, { mfaCode = it.filter(Char::isDigit).take(8) },
                            label = { Text("Verification code") },
                            singleLine = true,
                            enabled = !busy,
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                            modifier = Modifier.fillMaxWidth(),
                        )
                        TextButton(
                            onClick = { factorSent?.let { pickFactor(it) } },
                            enabled = !busy && resendIn <= 0,
                        ) { Text(if (resendIn > 0) "Send a new code (${resendIn}s)" else "Send a new code") }
                        TextButton(
                            onClick = { factorSent = null; mfaCode = "" },
                            enabled = !busy,
                        ) { Text("Choose a different method") }
                    }
                    loginId != null -> {
                        Text("Choose how to receive your verification code:")
                        Spacer(Modifier.size(8.dp))
                        factors.forEach { f ->
                            OutlinedButton(onClick = { pickFactor(f) }, enabled = !busy, modifier = Modifier.fillMaxWidth()) {
                                Text(f.label)
                            }
                        }
                    }
                    else -> {
                        Text(
                            "Sign in with your Church account (same as LCR) to re-authorize the daily sync. " +
                                "The session is stored encrypted — never your password — and is revocable anytime.",
                            style = MaterialTheme.typography.bodySmall,
                        )
                        Spacer(Modifier.size(8.dp))
                        OutlinedTextField(
                            username, { username = it },
                            label = { Text("Church username") },
                            singleLine = true,
                            enabled = !busy,
                            modifier = Modifier.fillMaxWidth(),
                        )
                        Spacer(Modifier.size(8.dp))
                        OutlinedTextField(
                            password, { password = it },
                            label = { Text("Password") },
                            singleLine = true,
                            enabled = !busy,
                            visualTransformation = PasswordVisualTransformation(),
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                            modifier = Modifier.fillMaxWidth(),
                        )
                    }
                }
                if (busy && status != null) {
                    Spacer(Modifier.size(8.dp))
                    Text(status ?: "", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.primary)
                }
                if (error != null) {
                    Spacer(Modifier.size(8.dp))
                    Text(error ?: "", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error)
                }
            }
        },
        confirmButton = {
            when {
                factorSent != null -> TextButton(onClick = { verify() }, enabled = !busy && mfaCode.length >= 6) {
                    Text("Verify & authorize")
                }
                loginId == null -> TextButton(onClick = { signIn() }, enabled = !busy && username.isNotBlank() && password.isNotEmpty()) {
                    Text("Authorize")
                }
                else -> Unit // factor-pick step: the factors themselves are the actions
            }
        },
        dismissButton = { TextButton(onClick = onDismiss, enabled = !busy) { Text("Cancel") } },
    )
}
