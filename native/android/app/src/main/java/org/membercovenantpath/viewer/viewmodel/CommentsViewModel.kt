package org.membercovenantpath.viewer.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import org.membercovenantpath.viewer.data.CommentsRepository
import org.membercovenantpath.viewer.model.Comment
import org.membercovenantpath.viewer.model.Member

data class CommentsUiState(
    val loading: Boolean = true,
    val comments: List<Comment> = emptyList(),
    val draft: String = "",
    val posting: Boolean = false,
    val error: String? = null,
)

/** Read + add leader notes for one member (member_comments, RLS-scoped). Mirrors `_CommentsSection`. */
class CommentsViewModel(
    private val member: Member,
    private val repo: CommentsRepository = CommentsRepository(),
) : ViewModel() {

    private val _state = MutableStateFlow(CommentsUiState())
    val state: StateFlow<CommentsUiState> = _state.asStateFlow()

    init { load() }

    fun onDraft(v: String) = _state.update { it.copy(draft = v) }

    private fun load() {
        val uuid = member.personUuid
        if (uuid.isNullOrEmpty()) { _state.update { it.copy(loading = false) }; return }
        viewModelScope.launch {
            _state.update { it.copy(loading = true) }
            runCatching { repo.load(uuid) }
                .onSuccess { rows -> _state.update { it.copy(loading = false, comments = rows) } }
                .onFailure { _state.update { it.copy(loading = false) } }
        }
    }

    fun post() {
        val body = _state.value.draft.trim()
        if (body.isEmpty() || member.personUuid.isNullOrEmpty()) return
        viewModelScope.launch {
            _state.update { it.copy(posting = true, error = null) }
            runCatching { repo.add(member, body) }
                .onSuccess { _state.update { it.copy(posting = false, draft = "") }; load() }
                .onFailure { e -> _state.update { it.copy(posting = false, error = "Could not post note: ${e.message}") } }
        }
    }
}

/** Factory so the screen can pass the [Member] into [CommentsViewModel]. */
class CommentsViewModelFactory(private val member: Member) : androidx.lifecycle.ViewModelProvider.Factory {
    @Suppress("UNCHECKED_CAST")
    override fun <T : ViewModel> create(modelClass: Class<T>): T = CommentsViewModel(member) as T
}
