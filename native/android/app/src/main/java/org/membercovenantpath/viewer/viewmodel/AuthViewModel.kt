package org.membercovenantpath.viewer.viewmodel

import android.content.Context
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import io.github.jan.supabase.auth.status.SessionStatus
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
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
    // "Send a new code" cooldown (seconds) — nudges the member to wait for the FRESH code instead
    // of typing one from an earlier text/screen (the 2026-06-11 stranded-at-MFA failure).
    val resendInSec: Int = 0,

    // Email code
    val email: String = "",
    val emailCode: String = "",
    val emailCodeSent: Boolean = false,
    val useRelay: Boolean = false,

    // #8: consent is no longer a checkbox on the login form; this is the internal "this auth pass
    // should enroll" flag, set just before we re-authenticate with consent after the post-login offer.
    val authorizeSync: Boolean = false,
    // #8: post-login offer to set up / improve daily sync (shown as a dialog) when the stake has no
    // sufficient credential. null = no offer pending.
    val enrollOffer: EnrollOffer? = null,

    // "Sign in on the Church website" — presents the in-app WebView at churchofjesuschrist.org so
    // the password is entered/autofilled ON the Church page, never in our UI.
    val showChurchWeb: Boolean = false,
) {
    data class EnrollOffer(val stake: String, val improving: Boolean)

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
        viewModelScope.launch { broker.warmUp() } // N5: warm the broker at startup, before submit
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
    // Codes are bare digits; people paste "123 456" / "123-456" from a text.
    fun onMfaCode(v: String) = _login.update { it.copy(mfaCode = v.filter(Char::isDigit).take(8), error = null) }
    fun onEmail(v: String) = _login.update { it.copy(email = v, error = null) }
    fun onEmailCode(v: String) = _login.update { it.copy(emailCode = v, error = null) }

    private fun reset(base: LoginUiState): LoginUiState {
        resendJob?.cancel()
        return base.copy(
            loginId = null, factors = emptyList(), factorSent = null, mfaCode = "", resendInSec = 0,
            emailCodeSent = false, emailCode = "", error = null, status = null,
        )
    }

    // Input typed for the OLD factor must never ride into a new challenge (2026-06-11).
    fun backToFactors() = _login.update { it.copy(factorSent = null, mfaCode = "", error = null) }
    fun backToPassword() = _login.update { reset(it) }

    private var resendJob: Job? = null

    private fun startResendCooldown() {
        resendJob?.cancel()
        _login.update { it.copy(resendInSec = 30) }
        resendJob = viewModelScope.launch {
            while (_login.value.resendInSec > 0) {
                delay(1_000)
                _login.update { it.copy(resendInSec = (it.resendInSec - 1).coerceAtLeast(0)) }
            }
        }
    }
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

    /** #8: holds the original (view-only) result while the post-login enroll offer is shown, so a
     *  "Not now" can still adopt that session. */
    private var pendingResult: BrokerResult? = null

    // ---- Church account ----
    // A consenting login (enroll) uses the credential-capture (one-MFA) flow (/auth/web/*) so the
    // single MFA mints the 45-day sync token; a plain view-only sign-in uses the light /auth/password.
    // authorizeSync IS the enroll flag (set when the post-login offer is accepted), so it routes the
    // shared MFA steps to the right backend pending store.
    private val webMode get() = _login.value.authorizeSync

    fun churchSignIn() = run {
        val r = if (_login.value.authorizeSync)
            broker.webStart(_login.value.username.trim(), _login.value.password, enroll = true)
        else broker.password(_login.value.username.trim(), _login.value.password, enroll = false)
        if (r.mfaRequired) {
            _login.update { it.copy(loginId = r.loginId, factors = r.factors) }
            if (r.factors.size == 1) selectFactorNow(r.factors.first())
            return@run
        }
        finishChurch(r)
    }

    /** After a successful Church login: block a no-access calling (N2); else, if the stake has no
     *  sufficient credential and this leader could set one up / improve a weaker one, raise the
     *  post-login offer (#8) instead of consuming. Otherwise adopt the session. */
    private suspend fun finishChurch(r: BrokerResult) {
        if (r.authorized == false) throw BrokerException(NO_ACCESS_MSG)
        if (!_login.value.authorizeSync && (r.canEnroll || r.canImprove)) {
            pendingResult = r
            _login.update {
                it.copy(enrollOffer = LoginUiState.EnrollOffer(r.stake ?: "Your stake", r.canImprove))
            }
            return
        }
        consume(r)
    }

    /** Accepted the post-login sync offer → re-authenticate WITH consent so the broker stores the
     *  credential (reuses the username/password still in state; handles MFA again if needed). */
    fun confirmEnroll() {
        pendingResult = null
        _login.update { it.copy(enrollOffer = null, authorizeSync = true) }
        churchSignIn()
    }

    /** Declined → adopt the original view-only session. */
    fun declineEnroll() {
        val r = pendingResult
        pendingResult = null
        _login.update { it.copy(enrollOffer = null) }
        if (r != null) run { consume(r) }
    }

    // ---- Church website (WebView capture — no password in our app) ----
    fun presentChurchWeb() = _login.update { it.copy(showChurchWeb = true, error = null) }
    fun dismissChurchWeb() = _login.update { it.copy(showChurchWeb = false) }

    /** The WebView captured the Church session cookies (the leader signed in on the Church's own
     *  page). Post them to the broker, which verifies the session and mints ours. We adopt the view
     *  session directly (N2-guarded) — NOT the post-login enroll offer, which re-auths with a
     *  password we deliberately never collected here. Setting up daily sync is a separate, explicit
     *  step (the re-auth dialog's "Authorize on the Church website" button, enroll=true). */
    fun churchWebLogin(cookies: List<Map<String, String>>) {
        _login.update { it.copy(showChurchWeb = false) }
        run {
            val r = broker.captureSession(cookies, enroll = false)
            if (r.authorized == false) throw BrokerException(NO_ACCESS_MSG)
            consume(r)
        }
    }

    fun selectFactor(f: BrokerFactor) = run { selectFactorNow(f) }
    private suspend fun selectFactorNow(f: BrokerFactor) {
        if (webMode) broker.webSelectFactor(_login.value.loginId!!, f.id)
        else broker.selectFactor(_login.value.loginId!!, f.id)
        // Fresh challenge → fresh input; the cooldown nudges waiting for the NEW code.
        _login.update { it.copy(factorSent = f, mfaCode = "") }
        startResendCooldown()
    }

    fun verifyMfa() = run {
        try {
            val r = if (webMode)
                broker.webVerify(_login.value.loginId!!, _login.value.mfaCode.trim(), enroll = true)
            else broker.verifyMfa(_login.value.loginId!!, _login.value.mfaCode.trim(), enroll = _login.value.authorizeSync)
            finishChurch(r)
        } catch (e: Throwable) {
            _login.update { it.copy(mfaCode = "") } // a rejected code must be retyped fresh
            throw e
        }
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
