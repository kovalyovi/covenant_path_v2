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
import org.membercovenantpath.viewer.data.CommentsRepository
import org.membercovenantpath.viewer.data.EnrollmentStatus
import org.membercovenantpath.viewer.data.MembersRepository
import org.membercovenantpath.viewer.logic.Freshness
import org.membercovenantpath.viewer.logic.NoteSummary
import org.membercovenantpath.viewer.logic.NotesIndex
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
    /** person_uuid -> newest leader note + count, for the list-row note lines. */
    val notes: Map<String, NoteSummary> = emptyMap(),
    val missionariesByUnit: Map<String, List<Missionary>> = emptyMap(),
    val refreshing: Boolean = false,
    val isAdmin: Boolean = false,
    // Owner-only maintenance mode (migration 0056): while `maintenanceMode` is on, everyone except the
    // owner sees a maintenance screen (the DB's RLS already returns no member rows to non-owners).
    val isOwner: Boolean = false,
    val maintenanceMode: Boolean = false,
    val maintenanceMessage: String? = null,
    val enrollStatus: EnrollmentStatus? = null,
    val syncing: Boolean = false,
    val syncStartedAt: String? = null,
) {
    val currentStake: Stake? get() = stakes.firstOrNull { it.id == currentStakeId }
    val stakeName: String? get() = currentStake?.name
    val lastSyncedAt: String? get() = currentStake?.lastSyncedAt
    /** A revoked OR stale sync credential → show the banner (stale = delegated Church session died,
     *  daily sync failing until a leader re-authorizes; matches the web `showStaleBanner`). */
    val staleCredential: Boolean
        get() = enrollStatus?.credential?.isRevoked == true || enrollStatus?.credential?.isStale == true

    /**
     * For a HEALTHY credential, nudge the PROVIDER (whose calling can read profiles) to re-authorize
     * and refresh patriarchal blessing — the one field the daily sync can't pull. Mirrors the web
     * `DashboardShell` gating: suppressed while the stale/revoked banner already prompts re-auth or a
     * sync runs; requires the provider + can_refresh_patriarchal + pending>0; and a 14-day GRACE
     * WINDOW since the last re-auth (credential.enrolledAt = its updated_at) so it doesn't nag right
     * after a refresh.
     */
    val showPatriarchalBanner: Boolean
        get() {
            if (staleCredential || syncing) return false
            val cred = enrollStatus?.credential ?: return false
            if (!cred.isProvider || !cred.canRefreshPatriarchal) return false
            if ((enrollStatus?.patriarchalPending ?: 0) <= 0) return false
            val graceMs = 14L * 24 * 60 * 60 * 1000
            val lastReauthMs = cred.enrolledAt
                ?.let { runCatching { Instant.parse(it).toEpochMilli() }.getOrNull() } ?: 0L
            // No known re-auth time, or older than the grace window → show it.
            return lastReauthMs == 0L || (System.currentTimeMillis() - lastReauthMs) > graceMs
        }
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
    private val comments: CommentsRepository = CommentsRepository(),
    private val prefs: AppPrefs,
) : ViewModel() {

    private val _state = MutableStateFlow(DashboardUiState())
    val state: StateFlow<DashboardUiState> = _state.asStateFlow()

    private var syncPollJob: Job? = null // N3: re-checks sync_state every ~5s while a sync runs

    init {
        bootstrap()
        checkAdmin()
        checkMaintenance()
        recordUsage()
    }

    /** Ops telemetry (0066): one name-free "opened the app" row per person per day, so the console
     *  can report how often units and callings actually use this. Best-effort, never blocking. */
    private fun recordUsage() {
        viewModelScope.launch { repo.recordAppOpen() }
    }

    private fun checkAdmin() {
        viewModelScope.launch { if (repo.isAdmin()) _state.update { it.copy(isAdmin = true) } }
    }

    /** Owner-only maintenance mode (migration 0056): read the global switch + whether this user is the
     *  owner, so the shell can show the maintenance screen to everyone else. Best-effort. */
    private fun checkMaintenance() {
        viewModelScope.launch {
            val status = repo.maintenanceStatus()
            val owner = repo.isOwner()
            _state.update {
                it.copy(maintenanceMode = status.maintenanceMode == true,
                        maintenanceMessage = status.maintenanceMessage, isOwner = owner)
            }
        }
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
                reloadNotes()
                // #11: prefetch enrollment status in the background (own coroutine) so opening Sync
                // settings is instant; it's also needed for the empty state.
                reloadEnrollStatus()
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
                    .onSuccess { m ->
                        _state.update { it.copy(members = m, load = LoadState.Ready) }
                        reloadNotes()
                    }
            }
        }
    }

    override fun onCleared() {
        syncPollJob?.cancel()
        super.onCleared()
    }

    /** Re-pull the notes index (one bulk RLS-scoped query). Best-effort: a notes hiccup must never
     *  fail the member load — rows just render without their note line. Also called after posting a
     *  note on the detail page so list rows show it immediately (mirrors web `reloadNotes`). */
    fun reloadNotes() {
        val id = _state.value.currentStakeId ?: return
        viewModelScope.launch {
            val notes = runCatching { NotesIndex.build(comments.stakeNotes(id)) }
                .getOrDefault(emptyMap())
            _state.update { it.copy(notes = notes) }
        }
    }

    /** (Re-)fetch enrollment status — also called after an in-app re-authorization so the
     *  stale/revoked banner + empty state clear without a sign-out (mirrors web `reloadEnrollStatus`). */
    fun reloadEnrollStatus() {
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
                .onSuccess { members ->
                    _state.update { it.copy(members = members, load = LoadState.Ready) }
                    reloadNotes()
                }
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
                .onSuccess { members ->
                    _state.update { it.copy(members = members, refreshing = false, load = LoadState.Ready) }
                    reloadNotes()
                }
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

    /** #5b: a stake leader toggles Google-Sheet generation; reflect it locally on success. */
    fun setSheetsEnabled(stakeId: String?, enabled: Boolean, onResult: (Boolean) -> Unit = {}) {
        if (stakeId == null) return
        viewModelScope.launch {
            runCatching { repo.setStakeSheetsEnabled(stakeId, enabled) }
                .onSuccess {
                    _state.update { s -> s.copy(stakes = s.stakes.map {
                        if (it.id == stakeId) it.copy(sheetsEnabled = enabled) else it
                    }) }
                    onResult(true)
                }
                .onFailure { onResult(false) }
        }
    }

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
