package org.membercovenantpath.viewer.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import org.membercovenantpath.viewer.data.AdminClient
import org.membercovenantpath.viewer.data.AdminRepository
import org.membercovenantpath.viewer.data.AuthRepository
import org.membercovenantpath.viewer.data.str
import org.membercovenantpath.viewer.model.AppAdmin

/** Each admin panel loads independently — a slow/failed section only affects its own card. */
sealed interface Panel<out T> {
    data object Loading : Panel<Nothing>
    data class Error(val message: String) : Panel<Nothing>
    data class Ready<T>(val data: T) : Panel<T>
}

data class AdminUiState(
    val summary: Panel<JsonObject> = Panel.Loading,
    val diagnostics: Panel<JsonObject> = Panel.Loading,
    val actions: Panel<JsonObject> = Panel.Loading,
    val stakes: Panel<JsonObject> = Panel.Loading,
    val admins: Panel<List<AppAdmin>> = Panel.Loading,
    val busy: Boolean = false,
    val toast: String? = null,
)

/**
 * Admin/Ops console state. Mirrors admin_page.dart: five independently-loaded panels (health/freshness/
 * maintenance + diagnostics + GitHub Actions + enrolled stakes + admins), maintenance dispatches and
 * re-runs through the broker, stake revoke/sync, and admin invite/revoke. Admin-gated server-side.
 */
class AdminViewModel(
    private val auth: AuthRepository = AuthRepository(),
    private val adminRepo: AdminRepository = AdminRepository(),
) : ViewModel() {

    private fun client() = AdminClient(auth.accessToken ?: "")

    private val _state = MutableStateFlow(AdminUiState())
    val state: StateFlow<AdminUiState> = _state.asStateFlow()

    init { loadAll() }

    fun loadAll() {
        _state.update {
            it.copy(
                summary = Panel.Loading, diagnostics = Panel.Loading, actions = Panel.Loading,
                stakes = Panel.Loading, admins = Panel.Loading,
            )
        }
        val c = client()
        launchPanel({ c.summary() }) { p -> _state.update { it.copy(summary = p) } }
        launchPanel({ c.diagnostics() }) { p -> _state.update { it.copy(diagnostics = p) } }
        launchPanel({ c.actions() }) { p -> _state.update { it.copy(actions = p) } }
        launchPanel({ c.enrolledStakes() }) { p -> _state.update { it.copy(stakes = p) } }
        viewModelScope.launch {
            runCatching { adminRepo.loadAdmins() }
                .onSuccess { rows -> _state.update { it.copy(admins = Panel.Ready(rows)) } }
                .onFailure { e -> _state.update { it.copy(admins = Panel.Error(e.message ?: "Failed")) } }
        }
    }

    private fun launchPanel(call: suspend () -> JsonObject, set: (Panel<JsonObject>) -> Unit) {
        viewModelScope.launch {
            runCatching { call() }
                .onSuccess { set(Panel.Ready(it)) }
                .onFailure { e -> set(Panel.Error(e.message ?: "Failed")) }
        }
    }

    private fun toast(m: String) = _state.update { it.copy(toast = m) }
    fun clearToast() = _state.update { it.copy(toast = null) }

    private fun guard(block: suspend () -> Unit) {
        viewModelScope.launch {
            _state.update { it.copy(busy = true) }
            runCatching { block() }.onFailure { toast(it.message ?: "$it") }
            _state.update { it.copy(busy = false) }
        }
    }

    /** Dispatch the daily-sync workflow with the given inputs (Full/Supabase/Sheets/Photos/per-stake). */
    fun dispatch(label: String, inputs: Map<String, String>) = guard {
        client().run("daily-sync.yml", buildJsonObject {
            inputs.forEach { (k, v) -> put(k, JsonPrimitive(v)) }
        })
        toast("$label dispatched. Refresh in a minute to see the run.")
        loadAll()
    }

    fun rerun(id: Long) = guard {
        client().rerun(id)
        toast("Re-run requested for #$id.")
        loadAll()
    }

    fun revokeStake(stakeId: String, name: String) = guard {
        client().revokeStake(stakeId)
        toast("Revoked sync for $name.")
        loadAll()
    }

    /** Wipe a stake's member data (keeps the stake + roles + credential; repopulates next sync). */
    fun wipeStakeData(stakeId: String, name: String) = guard {
        client().wipeStakeData(stakeId)
        toast("Wiped member data for $name.")
        loadAll()
    }

    /** Remove a stake completely (credential + members + roles + the stake row). Irreversible. */
    fun removeStake(stakeId: String, name: String) = guard {
        client().removeStake(stakeId)
        toast("Removed $name completely.")
        loadAll()
    }

    fun syncStake(unitNumber: String, name: String) {
        if (unitNumber.isBlank() || unitNumber == "null") {
            toast("No unit number on file for $name — can't scope a sync.")
            return
        }
        dispatch("Sync $name", mapOf("stake" to unitNumber, "targets" to "supabase"))
    }

    fun inviteAdmin(email: String) = guard {
        val res = client().invite(email)
        val status = res.str("status")
        toast(
            when (status) {
                "already_admin" -> "$email is already an admin."
                "pending_owner_approval" -> "Request sent — the owner must approve $email by email."
                else -> "$email: $status"
            },
        )
        loadAll()
    }

    fun revokeAdmin(email: String) = guard {
        adminRepo.revokeAdmin(email)
        toast("Revoked $email.")
        loadAll()
    }

    val currentEmail: String? get() = auth.currentEmail
}
