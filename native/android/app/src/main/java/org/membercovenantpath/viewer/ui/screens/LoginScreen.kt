package org.membercovenantpath.viewer.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import org.membercovenantpath.viewer.viewmodel.AuthViewModel
import org.membercovenantpath.viewer.viewmodel.LoginStep

/**
 * Email-OTP login (the only login in the PoC). Email field → "Send code" → 6-digit code field →
 * "Verify & sign in". Mirrors login_page.dart's email-code path.
 */
@Composable
fun LoginScreen(vm: AuthViewModel) {
    val s by vm.login.collectAsStateWithLifecycle()

    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Column(
            modifier = Modifier
                .widthIn(max = 380.dp)
                .verticalScroll(rememberScrollState())
                .padding(24.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text("Covenant Path", style = MaterialTheme.typography.headlineSmall)
            Text(
                "Read-only dashboard for stake & ward leaders. Sign in with the email your stake " +
                    "has on file.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                textAlign = TextAlign.Center,
                modifier = Modifier.padding(top = 8.dp, bottom = 20.dp),
            )

            OutlinedTextField(
                value = s.email,
                onValueChange = vm::onEmailChange,
                label = { Text("Email") },
                singleLine = true,
                enabled = !s.busy && s.step == LoginStep.EnterEmail,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email),
                modifier = Modifier.fillMaxWidth(),
            )

            if (s.step == LoginStep.EnterCode) {
                OutlinedTextField(
                    value = s.code,
                    onValueChange = vm::onCodeChange,
                    label = { Text("6-digit code") },
                    singleLine = true,
                    enabled = !s.busy,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                    modifier = Modifier.fillMaxWidth().padding(top = 12.dp),
                )
            }

            Button(
                onClick = { if (s.step == LoginStep.EnterEmail) vm.sendCode() else vm.verifyCode() },
                enabled = !s.busy,
                modifier = Modifier.fillMaxWidth().padding(top = 16.dp),
            ) {
                if (s.busy) {
                    CircularProgressIndicator(strokeWidth = 2.dp, modifier = Modifier.size(18.dp))
                } else {
                    Text(if (s.step == LoginStep.EnterEmail) "Send code" else "Verify & sign in")
                }
            }

            if (s.step == LoginStep.EnterCode) {
                TextButton(onClick = vm::backToEmail, enabled = !s.busy) {
                    Text("Use a different email")
                }
            }

            if (s.error != null) {
                Text(
                    s.error!!,
                    color = MaterialTheme.colorScheme.error,
                    style = MaterialTheme.typography.bodySmall,
                    modifier = Modifier.padding(top = 12.dp),
                )
            }
        }
    }
}
