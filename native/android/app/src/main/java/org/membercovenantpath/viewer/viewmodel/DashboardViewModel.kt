package org.membercovenantpath.viewer.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import org.membercovenantpath.viewer.data.AppPrefs
import org.membercovenantpath.viewer.data.BrokerClient
import org.membercovenantpath.viewer.data.EnrollmentStatus
import org.membercovenantpath.viewer.data.MembersRepository
import org.membercovenantpath.viewer.logic.Freshness
import org.membercovenantpath.viewer.model.Member
import org.membercovenantpath.viewer.model.Missionary
import org.membercovenantpath.viewer.model.Stake
import java.time.Instant
import java.time.temporal.ChronoUnit

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
    val isAdmin: Boolean = false,
    val enrollStatus: EnrollmentStatus? = null,
    val syncing: Boolean = false,
    val syncStartedAt: String? = null,
) {
    val currentStake: Stake? get() = stakes.firstOrNull { it.id == currentStakeId }
    val stakeName: String? get() = currentStake?.name
    val lastSyncedAt: String? get() = currentStake?.lastSyncedAt
    /** A revoked sync credential → show the re-enroll banner (matches dashboard_page staleCred). */
    val staleCredential: Boolean get() = enrollStatus?.credential?.isRevoked == true
}

/**
 * Owns the dashboard's data + chrome state. Mirrors dashboard_page.dart: resolve the single stake to
 * show (remembered choice → freshest) BEFORE the first member query, scope members to that stake,
 * check admin, derive the syncing banner from stakes.sync_state, load enrollment status when empty,
 * and drive sync-now. We never merge across stakes.
 */
class DashboardViewModel(
    private val repo: MembersRepository = MembersRepository(),
    private val broker: BrokerClient = BrokerClient(),
    private val prefs: AppPrefs,
) : ViewModel() {

    private val _state = MutableStateFlow(DashboardUiState())
    val state: StateFlow<DashboardUiState> = _state.asStateFlow()

    private var syncPollJob: Job? = null // N3: re-checks sync_state every ~5s while a sync runs

    init {
        bootstrap()
        checkAdmin()
    }

    private fun checkAdmin() {
        viewModelScope.launch { if (repo.isAdmin()) _state.update { it.copy(isAdmin = true) } }
    }

    private fun bootstrap() {
        viewModelScope.launch {
            _state.update { it.copy(load = LoadState.Loading) }
            runCatching {
                val stakes = repo.loadStakes()
                val remembered = prefs.currentStakeIdNow()
                val current = remembered?.takeIf { id -> stakes.any { it.id == id } } ?: stakes.firstOrNull()?.id
                _state.update { it.copy(stakes = stakes, currentStakeId = current) }
                applyStakeMeta()
                if (current != null) repo.loadMembers(current) else emptyList()
            }.onSuccess { members ->
                _state.update { it.copy(members = members, load = LoadState.Ready) }
                if (members.isEmpty()) loadEnrollStatus()
            }.onFailure { e ->
                _state.update { it.copy(load = LoadState.Error(e.message ?: "Could not load data.")) }
            }
        }
    }

    /** Recompute single-stake chrome (missionaries + syncing banner) from the selected stake only. */
    private fun applyStakeMeta() {
        val s = _state.value
        val stake = s.currentStake ?: return
        var running: String? = null
        if (stake.syncState == "running") {
            val started = Freshness.parseInstant(stake.syncStartedAt)
            // only "syncing" if it started recently — guards a crashed run that never marked done
            if (started != null && ChronoUnit.MINUTES.between(started, Instant.now()) < 30) {
                running = stake.syncStartedAt
            }
        }
        _state.update {
            it.copy(
                missionariesByUnit = repo.missionariesByUnit(stake),
                syncing = running != null,
                syncStartedAt = running,
            )
        }
        startSyncPollIfNeeded()
    }

    /** N3: while a sync runs, re-check stakes.sync_state every ~5s so the "syncing…" banner
     * self-clears and fresh members load without a manual refresh. The loop self-terminates when
     * syncing turns false (incl. the 30-min crashed-run guard in applyStakeMeta). */
    private fun startSyncPollIfNeeded() {
        if (!_state.value.syncing || syncPollJob?.isActive == true) return
        syncPollJob = viewModelScope.launch {
            while (_state.value.syncing) {
                delay(5000)
                runCatching {
                    val stakes = repo.loadStakes()
                    _state.update { it.copy(stakes = stakes) }
                    applyStakeMeta() // recomputes syncing; the isActive guard prevents a 2nd loop
                }
            }
            // sync finished → pull the fresh members
            _state.value.currentStakeId?.let { id ->
                runCatching { repo.loadMembers(id) }
                    .onSuccess { m -> _state.update { it.copy(members = m, load = LoadState.Ready) } }
            }
        }
    }

    override fun onCleared() {
        syncPollJob?.cancel()
        super.onCleared()
    }

    private fun loadEnrollStatus() {
        if (!broker.available) return
        viewModelScope.launch {
            runCatching { broker.enrollmentStatus() }
                .onSuccess { s -> _state.update { it.copy(enrollStatus = s) } }
        }
    }

    fun switchStake(id: String) {
        if (id == _state.value.currentStakeId) return
        _state.update { it.copy(currentStakeId = id, load = LoadState.Loading) }
        applyStakeMeta()
        viewModelScope.launch {
            runCatching { prefs.setCurrentStakeId(id) }
            runCatching { repo.loadMembers(id) }
                .onSuccess { members -> _state.update { it.copy(members = members, load = LoadState.Ready) } }
                .onFailure { e -> _state.update { it.copy(load = LoadState.Error(e.message ?: "Could not load data.")) } }
        }
    }

    fun refresh() {
        val id = _state.value.currentStakeId
        if (id == null) { bootstrap(); return }
        viewModelScope.launch {
            _state.update { it.copy(refreshing = true) }
            // also re-pull stake meta so the freshness chip + syncing banner update on refresh
            runCatching {
                val stakes = repo.loadStakes()
                _state.update { it.copy(stakes = stakes) }
                applyStakeMeta()
                repo.loadMembers(id)
            }
                .onSuccess { members -> _state.update { it.copy(members = members, refreshing = false, load = LoadState.Ready) } }
                .onFailure { _state.update { it.copy(refreshing = false) } }
        }
    }

    /** Ensure enrollment status is loaded (e.g. before opening the Sync settings sheet). */
    fun ensureEnrollStatus(onDone: (EnrollmentStatus?) -> Unit = {}) {
        val cached = _state.value.enrollStatus
        if (cached != null) { onDone(cached); return }
        viewModelScope.launch {
            val s = runCatching { broker.enrollmentStatus() }.getOrNull()
            if (s != null) _state.update { it.copy(enrollStatus = s) }
            onDone(s)
        }
    }

    /** Provider sync-now: optimistic in-progress, then reconcile with stakes.sync_state after a delay. */
    fun syncNow(onResult: (Boolean, String?) -> Unit) {
        viewModelScope.launch {
            runCatching { broker.syncNow() }
                .onSuccess { res ->
                    val partial = res["coverage_complete"]?.toString() == "false"
                    _state.update { it.copy(syncing = true, syncStartedAt = Instant.now().toString()) }
                    startSyncPollIfNeeded()
                    onResult(true, if (partial) "partial" else null)
                    delay(8000)
                    runCatching {
                        val stakes = repo.loadStakes()
                        _state.update { it.copy(stakes = stakes) }
                        applyStakeMeta()
                    }
                }
                .onFailure { e -> onResult(false, e.message) }
        }
    }

    fun revoke(onResult: (Boolean, String?) -> Unit) {
        val stakeId = _state.value.enrollStatus?.stakeId ?: return
        viewModelScope.launch {
            runCatching { broker.revoke(stakeId) }
                .onSuccess {
                    _state.update { it.copy(enrollStatus = null) }
                    onResult(true, null)
                }
                .onFailure { e -> onResult(false, e.message) }
        }
    }

    fun signOutToReenroll(signOut: () -> Unit) = signOut()

    /**
     * One-time, dismissible passkey upsell (#25): the first time the user reaches the app — and only
     * where passkeys work (broker configured) — suggest adding one. Remembered so we never nag.
     */
    fun maybeSuggestPasskey(onSuggest: () -> Unit) {
        if (!broker.available) return
        viewModelScope.launch {
            if (prefs.passkeySuggested()) return@launch
            prefs.markPasskeySuggested()
            onSuggest()
        }
    }
}
