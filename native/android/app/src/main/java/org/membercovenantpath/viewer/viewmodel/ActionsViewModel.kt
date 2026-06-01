package org.membercovenantpath.viewer.viewmodel

import android.content.Context
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject
import org.membercovenantpath.viewer.data.AdminClient
import org.membercovenantpath.viewer.data.AuthRepository
import org.membercovenantpath.viewer.data.BrokerClient
import org.membercovenantpath.viewer.data.PasskeyClient

/**
 * Secondary dashboard actions that hit the broker/admin: contact support, send feedback (→ GitHub
 * issue), generate + email report, add a passkey. Results come back via [onResult] so the screen can
 * show a snackbar. Mirrors the dashboard_page.dart action methods.
 */
class ActionsViewModel(
    private val auth: AuthRepository = AuthRepository(),
    private val broker: BrokerClient = BrokerClient(),
    private val passkey: PasskeyClient = PasskeyClient(),
) : ViewModel() {

    fun contact(subject: String, message: String, onResult: (Boolean, String) -> Unit) {
        if (message.isBlank()) return
        viewModelScope.launch {
            runCatching { broker.contact(subject.trim(), message.trim()) }
                .onSuccess { onResult(true, "Message sent — thank you!") }
                .onFailure { onResult(false, "Couldn't send: ${it.message}") }
        }
    }

    fun feedback(title: String, body: String, onResult: (Boolean, String) -> Unit) {
        if (title.isBlank()) return
        viewModelScope.launch {
            runCatching { AdminClient(auth.accessToken ?: "").feedback(title.trim(), body.trim()) }
                .onSuccess { res ->
                    val num = res["number"]?.toString()
                    val copilot = res["copilot"]?.toString() == "true"
                    onResult(true, "Thanks! Filed issue #$num${if (copilot) " — assigned to Copilot" else ""}")
                }
                .onFailure { onResult(false, "Couldn't send feedback: ${it.message}") }
        }
    }

    /** Build the scope report; hands the JSON to [onReport] for the sheet, or an error to [onError]. */
    fun report(onReport: (JsonObject) -> Unit, onError: (String) -> Unit) {
        if (!broker.available) { onError("Reports need Church-account login configured."); return }
        viewModelScope.launch {
            runCatching { broker.report() }
                .onSuccess { onReport(it) }
                .onFailure { onError("Couldn't build report: ${it.message}") }
        }
    }

    fun emailReport(onResult: (Boolean, String) -> Unit) {
        viewModelScope.launch {
            runCatching { broker.emailReport() }
                .onSuccess { res -> onResult(true, "Report emailed to ${res["to"]?.toString()?.trim('"') ?: "you"}.") }
                .onFailure { onResult(false, "Couldn't email report: ${it.message}") }
        }
    }

    fun addPasskey(context: Context, onResult: (Boolean, String) -> Unit) {
        if (!passkey.available) { onResult(false, "Passkeys require the sign-in service (broker)."); return }
        viewModelScope.launch {
            runCatching { passkey.register(context) }
                .onSuccess { onResult(true, "Passkey added — next time, sign in with a passkey (no password).") }
                .onFailure { onResult(false, "Could not add passkey: ${it.message}") }
        }
    }
}
