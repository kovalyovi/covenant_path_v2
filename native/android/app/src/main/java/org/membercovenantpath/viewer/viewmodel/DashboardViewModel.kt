package org.membercovenantpath.viewer.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import org.membercovenantpath.viewer.data.MembersRepository
import org.membercovenantpath.viewer.model.Member
import org.membercovenantpath.viewer.model.Missionary
import org.membercovenantpath.viewer.model.Stake

sealed interface LoadState {
    data object Loading : LoadState
    data class Error(val message: String) : LoadState
    data object Ready : LoadState
}

data class DashboardUiState(
    val load: LoadState = LoadState.Loading,
    val stakes: List<Stake> = emptyList(),
    val currentStakeId: String? = null,
    val members: List<Member> = emptyList(),
    val missionariesByUnit: Map<String, List<Missionary>> = emptyMap(),
    val refreshing: Boolean = false,
) {
    val currentStake: Stake? get() = stakes.firstOrNull { it.id == currentStakeId }
    val stakeName: String? get() = currentStake?.name
    val lastSyncedAt: String? get() = currentStake?.lastSyncedAt
}

/**
 * Owns the dashboard's data. Resolves the single stake to show BEFORE the first member query
 * (mirrors dashboard_page.dart `_bootstrap`), then loads members scoped to that stake. A
 * multi-stake power user can switch via [switchStake]; we never merge across stakes.
 */
class DashboardViewModel(
    private val repo: MembersRepository = MembersRepository(),
) : ViewModel() {

    private val _state = MutableStateFlow(DashboardUiState())
    val state: StateFlow<DashboardUiState> = _state.asStateFlow()

    init {
        bootstrap()
    }

    private fun bootstrap() {
        viewModelScope.launch {
            _state.update { it.copy(load = LoadState.Loading) }
            runCatching {
                val stakes = repo.loadStakes()
                val current = stakes.firstOrNull()?.id
                _state.update { it.copy(stakes = stakes, currentStakeId = current) }
                applyStakeMeta()
                if (current != null) repo.loadMembers(current) else emptyList()
            }.onSuccess { members ->
                _state.update { it.copy(members = members, load = LoadState.Ready) }
            }.onFailure { e ->
                _state.update { it.copy(load = LoadState.Error(e.message ?: "Could not load data.")) }
            }
        }
    }

    private fun applyStakeMeta() {
        val s = _state.value
        val stake = s.currentStake ?: return
        _state.update { it.copy(missionariesByUnit = repo.missionariesByUnit(stake)) }
    }

    fun switchStake(id: String) {
        if (id == _state.value.currentStakeId) return
        _state.update { it.copy(currentStakeId = id, load = LoadState.Loading) }
        applyStakeMeta()
        viewModelScope.launch {
            runCatching { repo.loadMembers(id) }
                .onSuccess { members -> _state.update { it.copy(members = members, load = LoadState.Ready) } }
                .onFailure { e -> _state.update { it.copy(load = LoadState.Error(e.message ?: "Could not load data.")) } }
        }
    }

    fun refresh() {
        val id = _state.value.currentStakeId
        if (id == null) {
            bootstrap()
            return
        }
        viewModelScope.launch {
            _state.update { it.copy(refreshing = true) }
            runCatching { repo.loadMembers(id) }
                .onSuccess { members ->
                    _state.update { it.copy(members = members, refreshing = false, load = LoadState.Ready) }
                }
                .onFailure { _state.update { it.copy(refreshing = false) } }
        }
    }
}
