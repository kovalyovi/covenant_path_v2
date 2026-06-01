package org.membercovenantpath.viewer.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject
import org.membercovenantpath.viewer.data.BrokerClient
import org.membercovenantpath.viewer.data.bool
import org.membercovenantpath.viewer.data.int
import org.membercovenantpath.viewer.data.str

/** Schedule section state (#21): the daily ET hour + paused, gated to eligibility. */
data class ScheduleState(
    val loaded: Boolean = false,
    val eligible: Boolean = false,
    val hourEt: Int = 7,
    val paused: Boolean = false,
    val busy: Boolean = false,
)

/** Google Drive section state (#21): raw broker /auth/google/status fields. */
data class DriveState(
    val loaded: Boolean = false,
    val eligible: Boolean = false,
    val configured: Boolean = false,
    val connected: Boolean = false,
    val needsReconnect: Boolean = false,
    val email: String? = null,
    val sheetUrl: String? = null,
    val lastSyncedAt: String? = null,
    val busy: Boolean = false,
)

/** Loads + writes the in-app sync schedule and Google Drive connection. Mirrors the two sub-sections
 * of `_SyncSettingsSheet`. Both are best-effort — they stay hidden if the broker can't report them. */
class SyncSettingsViewModel(
    private val broker: BrokerClient = BrokerClient(),
) : ViewModel() {

    private val _schedule = MutableStateFlow(ScheduleState())
    val schedule: StateFlow<ScheduleState> = _schedule.asStateFlow()

    private val _drive = MutableStateFlow(DriveState())
    val drive: StateFlow<DriveState> = _drive.asStateFlow()

    fun loadSchedule() {
        viewModelScope.launch {
            runCatching { broker.getSchedule() }
                .onSuccess { s ->
                    _schedule.value = ScheduleState(
                        loaded = true,
                        eligible = s.bool("eligible"),
                        hourEt = s.int("hour_et", 7),
                        paused = s.bool("paused"),
                    )
                }
                .onFailure { _schedule.update { it.copy(loaded = true) } }
        }
    }

    fun saveSchedule(hour: Int? = null, paused: Boolean? = null) {
        val h = hour ?: _schedule.value.hourEt
        val p = paused ?: _schedule.value.paused
        viewModelScope.launch {
            _schedule.update { it.copy(busy = true) }
            runCatching { broker.setSchedule(h, p) }
                .onSuccess { _schedule.update { it.copy(hourEt = h, paused = p, busy = false) } }
                .onFailure { _schedule.update { it.copy(busy = false) } }
        }
    }

    fun loadDrive() {
        viewModelScope.launch {
            runCatching { broker.googleDriveStatus() }
                .onSuccess { s -> _drive.value = parseDrive(s) }
                .onFailure { _drive.update { it.copy(loaded = true) } }
        }
    }

    /** Returns the OAuth URL to open (or null) — the caller launches it in a browser. */
    fun connectDrive(onUrl: (String?) -> Unit) {
        viewModelScope.launch {
            _drive.update { it.copy(busy = true) }
            val url = runCatching { broker.googleDriveStart().str("url") }.getOrNull()
            _drive.update { it.copy(busy = false) }
            onUrl(url)
        }
    }

    fun disconnectDrive() {
        viewModelScope.launch {
            _drive.update { it.copy(busy = true) }
            runCatching { broker.googleDriveDisconnect() }
            loadDrive()
            _drive.update { it.copy(busy = false) }
        }
    }

    private fun parseDrive(s: JsonObject) = DriveState(
        loaded = true,
        eligible = s.bool("eligible"),
        configured = s.bool("configured"),
        connected = s.bool("connected"),
        needsReconnect = s.bool("needs_reconnect"),
        email = s.str("email"),
        sheetUrl = s.str("sheet_url"),
        lastSyncedAt = s.str("last_synced_at"),
    )
}
