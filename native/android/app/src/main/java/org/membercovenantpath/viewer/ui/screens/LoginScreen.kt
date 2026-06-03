package org.membercovenantpath.viewer.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Fingerprint
import androidx.compose.material.icons.outlined.Shield
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import org.membercovenantpath.viewer.viewmodel.AuthViewModel
import org.membercovenantpath.viewer.viewmodel.LoginMode

/**
 * Sign-in (#3): three modes when the broker is configured — **Church account** (password → choose
 * MFA factor → enter code), **Email code** (send → verify, with a broker-relay backup), and a
 * **passkey** button; Email-only otherwise. Disclaimer + footer, a transient "waking up…" status
 * line, and an error line. Mirrors login_page.dart.
 */
@Composable
fun LoginScreen(vm: AuthViewModel) {
    val s by vm.login.collectAsStateWithLifecycle()
    val context = LocalContext.current

    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Column(
            modifier = Modifier.widthIn(max = 400.dp).verticalScroll(rememberScrollState()).padding(24.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text("Covenant Path", style = MaterialTheme.typography.headlineSmall)
            Spacer(Modifier.size(16.dp))

            if (s.brokerAvailable) {
                SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth()) {
                    SegmentedButton(
                        selected = s.mode == LoginMode.Church,
                        onClick = { vm.setMode(LoginMode.Church) },
                        shape = SegmentedButtonDefaults.itemShape(0, 2),
                        enabled = !s.busy,
                    ) { Text("Church account") }
                    SegmentedButton(
                        selected = s.mode == LoginMode.Email,
                        onClick = { vm.setMode(LoginMode.Email) },
                        shape = SegmentedButtonDefaults.itemShape(1, 2),
                        enabled = !s.busy,
                    ) { Text("Email code") }
                }
                Spacer(Modifier.size(20.dp))
            }

            if (s.mode == LoginMode.Church) ChurchFields(vm, s) else EmailFields(vm, s)

            if (s.passkeyAvailable) {
                Spacer(Modifier.size(16.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    HorizontalDivider(Modifier.weight(1f))
                    Text("or", color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(horizontal = 8.dp))
                    HorizontalDivider(Modifier.weight(1f))
                }
                Spacer(Modifier.size(16.dp))
                OutlinedButton(onClick = { vm.passkeySignIn(context) }, enabled = !s.busy, modifier = Modifier.fillMaxWidth()) {
                    Icon(Icons.Filled.Fingerprint, contentDescription = null, modifier = Modifier.size(18.dp))
                    Text("  Sign in with a passkey")
                }
            }

            if (s.busy && s.status != null) {
                Spacer(Modifier.size(12.dp))
                Text(s.status!!, color = MaterialTheme.colorScheme.primary, style = MaterialTheme.typography.bodySmall, textAlign = TextAlign.Center)
            }
            if (s.error != null) {
                Spacer(Modifier.size(12.dp))
                Text(s.error!!, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall, textAlign = TextAlign.Center)
            }
        }
    }
}

@Composable
private fun spinnerOr(busy: Boolean, label: String) {
    if (busy) CircularProgressIndicator(strokeWidth = 2.dp, modifier = Modifier.size(18.dp)) else Text(label)
}

@Composable
private fun ChurchFields(vm: AuthViewModel, s: org.membercovenantpath.viewer.viewmodel.LoginUiState) {
    when {
        // Step 3: enter the MFA code.
        s.factorSent != null -> {
            Text("Enter the code sent via ${s.factorSent.label}.", modifier = Modifier.fillMaxWidth())
            Spacer(Modifier.size(12.dp))
            OutlinedTextField(
                value = s.mfaCode, onValueChange = vm::onMfaCode, label = { Text("Verification code") },
                singleLine = true, enabled = !s.busy,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                modifier = Modifier.fillMaxWidth(),
            )
            Spacer(Modifier.size(16.dp))
            Button(onClick = vm::verifyMfa, enabled = !s.busy, modifier = Modifier.fillMaxWidth()) { spinnerOr(s.busy, "Verify & sign in") }
            TextButton(onClick = vm::backToFactors, enabled = !s.busy) { Text("Choose a different method") }
        }
        // Step 2: pick an MFA factor.
        s.loginId != null -> {
            Text("Choose how to receive your verification code:", modifier = Modifier.fillMaxWidth())
            Spacer(Modifier.size(8.dp))
            s.factors.forEach { f ->
                OutlinedButton(onClick = { vm.selectFactor(f) }, enabled = !s.busy, modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp)) { Text(f.label) }
            }
            TextButton(onClick = vm::backToPassword, enabled = !s.busy) { Text("Back") }
        }
        // Step 1: username + password.
        else -> {
            Text("Sign in with your Church account (same as LCR).", modifier = Modifier.fillMaxWidth())
            Spacer(Modifier.size(16.dp))
            OutlinedTextField(value = s.username, onValueChange = vm::onUsername, label = { Text("Church username") }, singleLine = true, enabled = !s.busy, modifier = Modifier.fillMaxWidth())
            Spacer(Modifier.size(12.dp))
            OutlinedTextField(
                value = s.password, onValueChange = vm::onPassword, label = { Text("Password") }, singleLine = true, enabled = !s.busy,
                visualTransformation = PasswordVisualTransformation(),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                modifier = Modifier.fillMaxWidth(),
            )
            Spacer(Modifier.size(10.dp))
            // Explicit, default-OFF authorization — signing in alone never captures the session.
            Row(verticalAlignment = Alignment.Top) {
                Checkbox(checked = s.authorizeSync, onCheckedChange = { vm.setAuthorizeSync(it) }, enabled = !s.busy)
                Spacer(Modifier.size(6.dp))
                Text(
                    "Authorize daily sync for my stake. Stores this Church session (encrypted — never your password) so your stake's data refreshes daily. Optional — leave it off to just view. Revoke anytime in Settings.",
                    style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(top = 12.dp),
                )
            }
            Spacer(Modifier.size(10.dp))
            Button(onClick = vm::churchSignIn, enabled = !s.busy, modifier = Modifier.fillMaxWidth()) { spinnerOr(s.busy, "Sign in") }
        }
    }
}

@Composable
private fun EmailFields(vm: AuthViewModel, s: org.membercovenantpath.viewer.viewmodel.LoginUiState) {
    Text("Sign in with the email your stake has on file.", modifier = Modifier.fillMaxWidth())
    if (s.useRelay) {
        Spacer(Modifier.size(8.dp))
        Row(verticalAlignment = Alignment.Top) {
            Icon(Icons.Outlined.Shield, contentDescription = null, tint = MaterialTheme.colorScheme.primary, modifier = Modifier.size(15.dp))
            Spacer(Modifier.size(6.dp))
            Text("Backup mode: signing in through our server (for networks that block Supabase).", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.primary)
        }
    }
    Spacer(Modifier.size(16.dp))
    OutlinedTextField(
        value = s.email, onValueChange = vm::onEmail, label = { Text("Email") }, singleLine = true,
        enabled = !s.busy && !s.emailCodeSent,
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email),
        modifier = Modifier.fillMaxWidth(),
    )
    if (s.emailCodeSent) {
        Spacer(Modifier.size(12.dp))
        OutlinedTextField(
            value = s.emailCode, onValueChange = vm::onEmailCode, label = { Text("6-digit code") }, singleLine = true, enabled = !s.busy,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
            modifier = Modifier.fillMaxWidth(),
        )
    }
    Spacer(Modifier.size(16.dp))
    Button(
        onClick = { if (s.emailCodeSent) vm.verifyEmailCode() else vm.sendEmailCode() },
        enabled = !s.busy, modifier = Modifier.fillMaxWidth(),
    ) { spinnerOr(s.busy, if (s.emailCodeSent) "Verify & sign in" else "Send code") }

    if (s.emailCodeSent) {
        TextButton(onClick = vm::useDifferentEmail, enabled = !s.busy) { Text("Use a different email") }
    }
    if (s.brokerAvailable && !s.useRelay) {
        TextButton(onClick = { vm.setRelay(true) }, enabled = !s.busy) { Text("Can't connect? Use backup sign-in") }
    }
    if (s.useRelay) {
        TextButton(onClick = { vm.setRelay(false) }, enabled = !s.busy) { Text("Use normal sign-in") }
    }
}
