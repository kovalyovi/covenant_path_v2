package org.membercovenantpath.viewer.ui.screens

import org.membercovenantpath.viewer.ui.AppBiometric
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Fingerprint
import androidx.compose.material.icons.outlined.Lock
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.fragment.app.FragmentActivity

/**
 * Shows [content] once unlocked. When the app-lock pref is on and the device supports biometrics,
 * prompts on entry; otherwise shows content immediately (fail-open on availability so a device
 * without biometrics is never locked out). Mirrors biometric_gate.dart's BiometricGate.
 */
@Composable
fun BiometricGate(lockEnabled: Boolean, content: @Composable () -> Unit) {
    val activity = LocalContext.current as? FragmentActivity
    val shouldLock = lockEnabled && activity != null && AppBiometric.available(activity)

    var unlocked by remember { mutableStateOf(!shouldLock) }
    var prompting by remember { mutableStateOf(false) }
    // Each increment fires one prompt attempt (entry + every "Unlock" tap).
    var attempt by remember { mutableIntStateOf(if (shouldLock) 1 else 0) }

    LaunchedEffect(attempt) {
        if (attempt > 0 && !unlocked && activity != null) {
            prompting = true
            unlocked = AppBiometric.authenticate(activity)
            prompting = false
        }
    }

    if (unlocked) {
        content()
        return
    }

    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Icon(
                Icons.Outlined.Lock,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.primary,
                modifier = Modifier.size(48.dp),
            )
            Text("Covenant Path is locked", modifier = Modifier.padding(top = 16.dp))
            if (prompting) {
                CircularProgressIndicator(modifier = Modifier.padding(top = 16.dp))
            } else {
                Button(onClick = { attempt++ }, modifier = Modifier.padding(top = 16.dp)) {
                    Icon(Icons.Filled.Fingerprint, contentDescription = null, modifier = Modifier.size(18.dp))
                    Text("  Unlock")
                }
            }
        }
    }
}
