package org.membercovenantpath.viewer.viewmodel

import android.content.Context
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
import org.membercovenantpath.viewer.data.AppConfig
import org.membercovenantpath.viewer.data.AuthRepository
import org.membercovenantpath.viewer.data.BrokerClient
import org.membercovenantpath.viewer.data.BrokerException
import org.membercovenantpath.viewer.data.BrokerFactor
import org.membercovenantpath.viewer.data.BrokerResult
import org.membercovenantpath.viewer.data.PasskeyClient
import org.membercovenantpath.viewer.data.str

/** High-level auth gate state the UI routes on. */
enum class AuthGate { Loading, SignedOut, SignedIn }

/** The three sign-in modes (segmented when the broker is configured; else Email only). */
enum class LoginMode { Church, Email }

/**
 * Login UI state mirroring login_page.dart: a Church-account flow (password → choose MFA factor →
 * enter code), an Email-code flow (send → verify, with a broker-relay backup), and an optional
 * passkey button. One resulting Supabase session either way; sessionStatus then flips [gate].
 */
data class LoginUiState(
    val mode: LoginMode = if (AppConfig.brokerAvailable) LoginMode.Church else LoginMode.Email,
    val busy: Boolean = false,
    val status: String? = null, // transient progress note ("waking up the sign-in service…")
    val error: String? = null,

    // Church account
    val username: String = "",
    val password: String = "",
    val loginId: String? = null,
    val factors: List<BrokerFactor> = emptyList(),
    val factorSent: BrokerFactor? = null,
    val mfaCode: String = "",

    // Email code
    val email: String = "",
    val emailCode: String = "",
    val emailCodeSent: Boolean = false,
    val useRelay: Boolean = false,
) {
    val brokerAvailable: Boolean get() = AppConfig.brokerAvailable
    val passkeyAvailable: Boolean get() = AppConfig.brokerAvailable
}

class AuthViewModel(
    private val repo: AuthRepository = AuthRepository(),
    private val broker: BrokerClient = BrokerClient(),
    private val passkey: PasskeyClient = PasskeyClient(),
) : ViewModel() {

    init {
        broker.onStatus = { msg -> _login.update { if (it.busy) it.copy(status = msg) else it } }
    }

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

    // ---- field setters ----
    fun setMode(m: LoginMode) = _login.update { reset(it.copy(mode = m)) }
    fun onUsername(v: String) = _login.update { it.copy(username = v, error = null) }
    fun onPassword(v: String) = _login.update { it.copy(password = v, error = null) }
    fun onMfaCode(v: String) = _login.update { it.copy(mfaCode = v, error = null) }
    fun onEmail(v: String) = _login.update { it.copy(email = v, error = null) }
    fun onEmailCode(v: String) = _login.update { it.copy(emailCode = v, error = null) }

    private fun reset(base: LoginUiState) = base.copy(
        loginId = null, factors = emptyList(), factorSent = null, mfaCode = "",
        emailCodeSent = false, emailCode = "", error = null, status = null,
    )

    fun backToFactors() = _login.update { it.copy(factorSent = null, error = null) }
    fun backToPassword() = _login.update { reset(it) }
    fun useDifferentEmail() = _login.update { it.copy(emailCodeSent = false, emailCode = "", error = null) }
    fun setRelay(on: Boolean) = _login.update { it.copy(useRelay = on, emailCodeSent = false, emailCode = "", error = null) }

    private fun run(block: suspend () -> Unit) {
        viewModelScope.launch {
            _login.update { it.copy(busy = true, error = null, status = null) }
            try {
                block()
                _login.update { it.copy(busy = false) }
            } catch (e: BrokerException) {
                _login.update { it.copy(busy = false, error = e.message) }
            } catch (e: Throwable) {
                _login.update { it.copy(busy = false, error = e.message ?: e.toString()) }
            }
        }
    }

    /** Turn a broker-minted OTP into a real Supabase session (gate then routes to the app). */
    // N2: shown when a Church login succeeds but the calling has no covenant-path access.
    private val NO_ACCESS_MSG =
        "This account doesn't have access to Covenant Path. Access is granted by your calling — " +
            "if you should have access, ask your stake leadership."

    private suspend fun consume(r: BrokerResult) {
        val email = r.email
        val otp = r.otp
        if (email == null || otp == null) throw BrokerException("Sign-in service did not return a session.")
        repo.verifyBrokerOtp(email, otp)
    }

    // ---- Church account ----
    fun churchSignIn() = run {
        val r = broker.password(_login.value.username.trim(), _login.value.password, enroll = true)
        if (r.mfaRequired) {
            _login.update { it.copy(loginId = r.loginId, factors = r.factors) }
            if (r.factors.size == 1) selectFactorNow(r.factors.first())
            return@run
        }
        if (r.authorized == false) throw BrokerException(NO_ACCESS_MSG)
        consume(r)
    }

    fun selectFactor(f: BrokerFactor) = run { selectFactorNow(f) }
    private suspend fun selectFactorNow(f: BrokerFactor) {
        broker.selectFactor(_login.value.loginId!!, f.id)
        _login.update { it.copy(factorSent = f) }
    }

    fun verifyMfa() = run {
        val r = broker.verifyMfa(_login.value.loginId!!, _login.value.mfaCode.trim(), enroll = true)
        if (r.authorized == false) throw BrokerException(NO_ACCESS_MSG)
        consume(r)
    }

    // ---- Email code ----
    fun sendEmailCode() {
        val email = _login.value.email.trim()
        if (email.isEmpty()) { _login.update { it.copy(error = "Enter your email.") }; return }
        run {
            if (_login.value.useRelay) broker.emailStart(email) else repo.sendEmailCode(email)
            _login.update { it.copy(emailCodeSent = true) }
        }
    }

    fun verifyEmailCode() {
        val s = _login.value
        if (s.emailCode.trim().isEmpty()) { _login.update { it.copy(error = "Enter the 6-digit code.") }; return }
        run {
            if (s.useRelay) {
                val t = broker.emailVerify(s.email.trim(), s.emailCode.trim())
                val refresh = t.str("refresh_token") ?: throw BrokerException("No session returned.")
                repo.adoptRefreshToken(refresh)
            } else {
                repo.verifyEmailCode(s.email, s.emailCode)
            }
        }
    }

    // ---- Passkey ----
    fun passkeySignIn(context: Context) = run {
        val r = passkey.login(context)
        consume(r)
    }

    fun signOut() {
        viewModelScope.launch { runCatching { repo.signOut() } }
        _login.value = LoginUiState()
    }
}
