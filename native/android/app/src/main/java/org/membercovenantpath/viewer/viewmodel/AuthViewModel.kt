package org.membercovenantpath.viewer.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import io.github.jan.supabase.auth.status.SessionStatus
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import org.membercovenantpath.viewer.data.AuthRepository

/** High-level auth gate state the UI routes on. */
enum class AuthGate { Loading, SignedOut, SignedIn }

/** Step of the email-OTP login form. */
enum class LoginStep { EnterEmail, EnterCode }

data class LoginUiState(
    val step: LoginStep = LoginStep.EnterEmail,
    val email: String = "",
    val code: String = "",
    val busy: Boolean = false,
    val error: String? = null,
)

class AuthViewModel(
    private val repo: AuthRepository = AuthRepository(),
) : ViewModel() {

    /** Maps supabase-kt's SessionStatus to a simple gate; starts Loading until the first emission. */
    val gate: StateFlow<AuthGate> = repo.sessionStatus
        .map { status ->
            when (status) {
                is SessionStatus.Authenticated -> AuthGate.SignedIn
                is SessionStatus.NotAuthenticated -> AuthGate.SignedOut
                is SessionStatus.Initializing -> AuthGate.Loading
                else -> AuthGate.Loading // RefreshFailure etc. → keep showing login
            }
        }
        .stateIn(viewModelScope, SharingStarted.Eagerly, AuthGate.Loading)

    private val _login = MutableStateFlow(LoginUiState())
    val login: StateFlow<LoginUiState> = _login.asStateFlow()

    val currentEmail: String? get() = repo.currentEmail

    fun onEmailChange(v: String) = _login.update { it.copy(email = v, error = null) }
    fun onCodeChange(v: String) = _login.update { it.copy(code = v, error = null) }

    fun backToEmail() = _login.update { it.copy(step = LoginStep.EnterEmail, code = "", error = null) }

    fun sendCode() {
        val email = _login.value.email.trim()
        if (email.isEmpty()) {
            _login.update { it.copy(error = "Enter your email.") }
            return
        }
        viewModelScope.launch {
            _login.update { it.copy(busy = true, error = null) }
            runCatching { repo.sendEmailCode(email) }
                .onSuccess { _login.update { it.copy(busy = false, step = LoginStep.EnterCode) } }
                .onFailure { e -> _login.update { it.copy(busy = false, error = e.message ?: "Could not send code.") } }
        }
    }

    fun verifyCode() {
        val s = _login.value
        if (s.code.trim().isEmpty()) {
            _login.update { it.copy(error = "Enter the 6-digit code.") }
            return
        }
        viewModelScope.launch {
            _login.update { it.copy(busy = true, error = null) }
            runCatching { repo.verifyEmailCode(s.email, s.code) }
                // On success, the sessionStatus flow flips gate → SignedIn; nothing else to do.
                .onFailure { e -> _login.update { it.copy(busy = false, error = e.message ?: "Invalid code.") } }
        }
    }

    fun signOut() {
        viewModelScope.launch { runCatching { repo.signOut() } }
        _login.value = LoginUiState()
    }
}
