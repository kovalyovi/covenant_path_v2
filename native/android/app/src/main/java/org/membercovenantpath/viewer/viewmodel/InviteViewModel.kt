package org.membercovenantpath.viewer.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import org.membercovenantpath.viewer.data.InviteRepository
import org.membercovenantpath.viewer.model.Invitation
import org.membercovenantpath.viewer.model.Unit as OrgUnit

data class InviteUiState(
    val loading: Boolean = true,
    val invitations: List<Invitation> = emptyList(),
    val units: List<OrgUnit> = emptyList(),
    val unitId: String? = null, // null => everything the inviter can see
    val email: String = "",
    val busy: Boolean = false,
    val message: String? = null,
    val ok: Boolean = false,
) {
    /** Collapse multiple scope rows per email (matches invite_page.dart byEmail). */
    val byEmail: List<Invitation>
        get() {
            val seen = LinkedHashMap<String, Invitation>()
            for (r in invitations) r.invitedEmail?.let { seen.putIfAbsent(it, r) }
            return seen.values.toList()
        }
}

/** Power-user invites/revokes via the escalation-safe RPCs. Mirrors invite_page.dart. */
class InviteViewModel(private val repo: InviteRepository = InviteRepository()) : ViewModel() {

    private val _state = MutableStateFlow(InviteUiState())
    val state: StateFlow<InviteUiState> = _state.asStateFlow()

    init { reload(); loadUnits() }

    fun onEmail(v: String) = _state.update { it.copy(email = v, message = null) }
    fun setUnit(id: String?) = _state.update { it.copy(unitId = id) }

    private fun reload() {
        viewModelScope.launch {
            _state.update { it.copy(loading = true) }
            runCatching { repo.loadInvitations() }
                .onSuccess { rows -> _state.update { it.copy(loading = false, invitations = rows) } }
                .onFailure { _state.update { it.copy(loading = false) } }
        }
    }

    private fun loadUnits() {
        viewModelScope.launch {
            val units = repo.loadUnits()
            _state.update { it.copy(units = units) }
        }
    }

    fun invite() {
        val email = _state.value.email.trim()
        if (email.isEmpty()) return
        viewModelScope.launch {
            _state.update { it.copy(busy = true, message = null) }
            runCatching { repo.invite(email, _state.value.unitId) }
                .onSuccess { n ->
                    _state.update {
                        it.copy(
                            busy = false, email = "", ok = true,
                            message = "Invited $email ($n scope${if (n == 1) "" else "s"}). They can sign in with that email.",
                        )
                    }
                    reload()
                }
                .onFailure { e -> _state.update { it.copy(busy = false, ok = false, message = "Could not invite: ${e.message}") } }
        }
    }

    fun revoke(email: String) {
        viewModelScope.launch {
            runCatching { repo.revoke(email) }
            reload()
        }
    }
}
