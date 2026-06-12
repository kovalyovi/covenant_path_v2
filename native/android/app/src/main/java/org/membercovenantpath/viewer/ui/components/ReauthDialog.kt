package org.membercovenantpath.viewer.ui.components

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.HorizontalDivider
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
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import org.membercovenantpath.viewer.data.AuthRepository
import org.membercovenantpath.viewer.data.BrokerClient
import org.membercovenantpath.viewer.data.BrokerException
import org.membercovenantpath.viewer.data.BrokerFactor
import org.membercovenantpath.viewer.data.BrokerResult
import org.membercovenantpath.viewer.logic.mfaPrompt

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
 *
 * USERNAME + PASSWORD ONLY (2026-06-12). Setting up daily sync mints a 45-day Member Tools token via
 * a silent SSO that needs the global Okta session only the classic username+password lane establishes
 * (/auth/web/*). The passwordless emailed-code (OTP) lane was removed: its Okta session is app-scoped
 * and could never mint the token. A leader who'd rather not type a password uses the Church-website
 * capture below (also enroll=true). See docs/DECISIONS.md (ADR-010).
 */
@Composable
fun ReauthDialog(onDismiss: () -> Unit, onSuccess: (String) -> Unit) {
    val broker = remember { BrokerClient() }
    val authRepo = remember { AuthRepository() }
    val scope = rememberCoroutineScope()

    var username by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    var mfaCode by remember { mutableStateOf("") }
    // "Authorize on the Church website" — the WebView capture lane (no password in our app).
    var showChurchWeb by remember { mutableStateOf(false) }
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

    // Enter (or re-enter) the MFA factor step. An MFA-enabled account may, after the first factor,
    // demand a DISTINCT factor (for Church accounts sometimes the password, 2026-06-12).
    suspend fun enterMfa(r: BrokerResult) {
        loginId = r.loginId
        factors = r.factors
        factorSent = null
        mfaCode = ""
        // Auto-send if there's exactly one factor (matches the login flow + web).
        if (r.factors.size == 1 && r.loginId != null) {
            broker.webSelectFactor(r.loginId!!, r.factors.first().id)
            factorSent = r.factors.first()
            resendIn = 30
        }
    }

    fun signIn() = step {
        // enroll=true: this IS the consent. The password lane IS the one-MFA credential-capture flow
        // (/auth/web/*) so the single MFA mints the 45-day sync token.
        val r = broker.webStart(username.trim(), password, enroll = true)
        if (r.mfaRequired) {
            enterMfa(r)
            return@step
        }
        finish(r)
    }

    fun pickFactor(f: BrokerFactor) = step {
        broker.webSelectFactor(loginId!!, f.id)
        // Fresh challenge → fresh input; the cooldown nudges waiting for the NEW code.
        factorSent = f
        mfaCode = ""
        resendIn = 30
    }

    fun verify() = step {
        try {
            val r = broker.webVerify(loginId!!, mfaCode.trim(), enroll = true)
            if (r.mfaRequired) {
                enterMfa(r) // chained continuation (rare): yet another factor owed
                return@step
            }
            finish(r)
        } catch (e: Throwable) {
            mfaCode = "" // a rejected code must be retyped fresh
            throw e
        }
    }

    // The Church web sheet captured a session (the leader authorized on churchofjesuschrist.org).
    // Post the cookies with enroll=true so the broker stores the sync credential, then finish.
    fun authorizeWithCaptured(cookies: List<Map<String, String>>) = step {
        val r = broker.captureSession(cookies, enroll = true)
        finish(r)
    }

    AlertDialog(
        onDismissRequest = { if (!busy) onDismiss() },
        title = { Text("Re-authorize daily sync") },
        text = {
            Column {
                when {
                    factorSent != null -> {
                        // Names the code's SOURCE (texted number vs authenticator app) — the
                        // wrong-source code is the multi-method trap (2026-06-11).
                        val tips = mfaPrompt(factorSent!!)
                        val isPassword = factorSent?.method == "password"
                        Text(tips.prompt)
                        tips.warning?.let {
                            Spacer(Modifier.size(4.dp))
                            Text(it, style = MaterialTheme.typography.bodySmall,
                                 color = MaterialTheme.colorScheme.primary)
                        }
                        Spacer(Modifier.size(8.dp))
                        if (isPassword) {
                            // MFA continuation: the next factor is the PASSWORD (a distinct factor
                            // type from a code) — not a 6-digit code.
                            OutlinedTextField(
                                mfaCode, { mfaCode = it },
                                label = { Text("Password") },
                                singleLine = true,
                                enabled = !busy,
                                visualTransformation = PasswordVisualTransformation(),
                                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                                modifier = Modifier.fillMaxWidth(),
                            )
                        } else {
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
                        }
                        tips.noCodeHint?.let {
                            Text(it, style = MaterialTheme.typography.bodySmall,
                                 color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                        TextButton(
                            onClick = { factorSent = null; mfaCode = "" },
                            enabled = !busy,
                        ) { Text("Choose a different method") }
                    }
                    loginId != null -> {
                        Text("Choose how to receive your verification code:")
                        Spacer(Modifier.size(8.dp))
                        factors.forEach { f ->
                            // vertical padding keeps the stacked factor options from rendering flush
                            // (matches LoginScreen + the web .form-stack gap)
                            OutlinedButton(onClick = { pickFactor(f) }, enabled = !busy, modifier = Modifier.fillMaxWidth().padding(vertical = 6.dp)) {
                                Text(f.label)
                            }
                        }
                    }
                    else -> {
                        Text(
                            "Sign in with your Church account (same username and password as LCR) to " +
                                "set up the daily sync. The session is stored encrypted — never your " +
                                "password — and is revocable anytime.",
                            style = MaterialTheme.typography.bodySmall,
                        )
                        Spacer(Modifier.size(4.dp))
                        Text(
                            "Daily sync needs your username and password — that's the only sign-in the " +
                                "Church lets us renew unattended for ~45 days. (An emailed code can sign " +
                                "you in to view, but can't authorize the background sync.)",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
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
                        // No password in our app: authorize by signing in on the Church's own web
                        // page. Best for an MFA-enabled account (the full Church MFA is there).
                        Spacer(Modifier.size(8.dp))
                        HorizontalDivider()
                        Spacer(Modifier.size(8.dp))
                        OutlinedButton(
                            onClick = { error = null; showChurchWeb = true },
                            enabled = !busy,
                            modifier = Modifier.fillMaxWidth(),
                        ) { Text("Authorize on the Church website instead") }
                        Text(
                            "Opens churchofjesuschrist.org — your password is entered there, never in this app.",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.padding(top = 4.dp),
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
                // A password isn't a 6-digit code — gate it on non-empty only.
                factorSent != null -> TextButton(
                    onClick = { verify() },
                    enabled = !busy && if (factorSent?.method == "password") mfaCode.isNotEmpty() else mfaCode.length >= 6,
                ) {
                    Text("Verify & authorize")
                }
                loginId == null -> TextButton(
                    onClick = { signIn() },
                    enabled = !busy && username.isNotBlank() && password.isNotEmpty(),
                ) { Text("Authorize") }
                else -> Unit // factor-pick step: the factors themselves are the actions
            }
        },
        dismissButton = { TextButton(onClick = onDismiss, enabled = !busy) { Text("Cancel") } },
    )

    if (showChurchWeb) {
        Dialog(
            onDismissRequest = { showChurchWeb = false },
            properties = DialogProperties(usePlatformDefaultWidth = false),
        ) {
            ChurchWebAuthSheet(
                isEnroll = true,
                onCapture = { cookies -> showChurchWeb = false; authorizeWithCaptured(cookies) },
                onCancel = { showChurchWeb = false },
            )
        }
    }
}
