import Foundation
import Observation
import Auth

/// App-wide auth state + the three login flows (Church account · Email code · Passkey), driving
/// `RootView`'s switch between Login and the Dashboard. Faithful port of the logic in
/// `login_page.dart` (`_run`/`_consume`/`_churchSignIn`/`_selectFactor`/`_verifyMfa`/`_sendEmailCode`/
/// `_verifyEmailCode`/`_passkeySignIn`) onto the Observation framework.
@MainActor
@Observable
public final class SessionStore {

    public enum Phase: Equatable {
        case loading          // initial: checking for an existing session
        case signedOut
        case signedIn
    }

    /// Which login tab is showing (segmented when the broker is configured; else Email only).
    public enum Mode: String, CaseIterable { case church, email
        public var label: String { self == .church ? "Church account" : "Email code" }
    }

    public private(set) var phase: Phase = .loading
    public var isBusy = false
    public var errorMessage: String?
    /// Transient progress note (e.g. "waking up the sign-in service").
    public var statusMessage: String?

    public var mode: Mode

    // Church-account flow state.
    public var loginID: String?
    public var factors: [BrokerFactor] = []
    public var factorSent: BrokerFactor?

    /// #8: post-login "set up / improve daily sync" offer, shown as an alert when the stake has no
    /// sufficient credential (consent is no longer a checkbox on the login form). Set after a
    /// successful sign-in; the View confirms (re-auth WITH consent) or declines (just sign in).
    public struct EnrollOffer: Identifiable, Equatable {
        public let id = UUID()
        public let stake: String
        public let improving: Bool
    }
    public var enrollOffer: EnrollOffer?
    private var pendingResult: BrokerResult?
    private var lastUsername = ""
    private var lastPassword = ""

    // Email-code flow state.
    public var emailCodeSent = false
    public var useRelay = false   // route email-code through the broker (blocked networks)

    /// "Sign in on the Church website" — presents the in-app WebView at churchofjesuschrist.org so
    /// the password is entered/autofilled ON the Church page, never in our UI (the captured session
    /// is posted to the broker). Drives a `.sheet` in `LoginView`.
    public var showChurchWebLogin = false

    private let auth: AuthService
    private let broker: BrokerService
    private let passkeyAvailableProvider: () -> Bool
    private let passkeyLogin: () async throws -> BrokerResult
    private var watchTask: Task<Void, Never>?

    public var brokerAvailable: Bool { broker.available }
    public var passkeyAvailable: Bool { passkeyAvailableProvider() }

    public init(auth: AuthService, broker: BrokerService,
                passkeyAvailable: @escaping () -> Bool = { false },
                passkeyLogin: @escaping () async throws -> BrokerResult = { throw BrokerError("Unavailable") }) {
        self.auth = auth
        self.broker = broker
        self.passkeyAvailableProvider = passkeyAvailable
        self.passkeyLogin = passkeyLogin
        self.mode = broker.available ? .church : .email
        Task { await broker.warmUp() } // N5: warm the broker at startup, before the user submits
        // Surface the broker's cold-start status line in the login screen.
        broker.onStatus = { [weak self] m in
            Task { @MainActor in self?.statusMessage = m }
        }
    }

    /// Resolve the initial phase and start listening for auth changes (port of AuthGate's stream).
    public func start() {
        Task { @MainActor in
            phase = (await auth.currentSession) != nil ? .signedIn : .signedOut
        }
        watchTask?.cancel()
        watchTask = Task { @MainActor [weak self] in
            guard let self else { return }
            for await change in auth.authStateChanges {
                switch change.event {
                case .signedIn, .tokenRefreshed, .userUpdated, .initialSession:
                    if change.session != nil { self.phase = .signedIn }
                case .signedOut:
                    self.phase = .signedOut
                    self.resetEmailEntry()
                    self.resetChurch()
                default:
                    break
                }
            }
        }
    }

    // MARK: - mode + reset

    public func selectMode(_ m: Mode) {
        mode = m
        reset()
    }

    public func reset() {
        resetChurch()
        resetEmailEntry()
        errorMessage = nil
    }

    private func resetChurch() {
        loginID = nil
        factors = []
        factorSent = nil
    }

    public func resetEmailEntry() {
        emailCodeSent = false
        errorMessage = nil
    }

    // MARK: - Church account

    /// The leader's explicit consent to store their session for daily sync. Default OFF — signing in
    /// no longer captures a credential automatically. Carried across the MFA steps so verifyMfa stores
    /// only when the leader authorized it.
    private var enrollConsent = false
    // A consenting login (enroll) uses the credential-capture (one-MFA) flow (/auth/web/*) so the
    // single MFA mints the 45-day sync token; a plain view-only sign-in uses the light /auth/password.
    // Carried across the MFA steps to route select/verify to the right backend pending store.
    private var webMode = false

    public func churchSignIn(username: String, password: String, authorizeSync: Bool = false) async {
        enrollConsent = authorizeSync
        webMode = authorizeSync
        lastUsername = username.trimmed   // stashed so a post-login enroll offer can re-auth (#8)
        lastPassword = password
        await run {
            let r: BrokerResult
            if authorizeSync {
                r = try await self.broker.webStart(username.trimmed, password, enroll: true)
            } else {
                r = try await self.broker.password(username.trimmed, password, enroll: false)
            }
            if r.mfaRequired {
                self.loginID = r.loginID
                self.factors = r.factors
                // Auto-send if there's exactly one factor (matches Flutter).
                if r.factors.count == 1 { await self.selectFactor(r.factors[0]) }
                return
            }
            try await self.finishChurch(r)
        }
    }

    /// After a successful Church login: block a no-access calling (N2); else, if the stake has no
    /// sufficient credential and this leader could set one up / improve a weaker one, raise the
    /// post-login offer (#8) instead of consuming. Otherwise adopt the session.
    private func finishChurch(_ r: BrokerResult) async throws {
        if r.authorized == false { throw BrokerError(SessionStore.noAccessMessage) }
        if !enrollConsent && (r.canEnroll || r.canImprove) {
            pendingResult = r
            enrollOffer = EnrollOffer(stake: r.stake ?? "Your stake", improving: r.canImprove)
            return
        }
        try await consume(r)
    }

    /// The leader accepted the post-login sync offer → re-authenticate WITH consent so the broker
    /// stores the credential (reuses the stashed username/password; handles MFA again if needed).
    public func confirmEnroll() async {
        enrollOffer = nil
        pendingResult = nil
        await churchSignIn(username: lastUsername, password: lastPassword, authorizeSync: true)
    }

    /// The leader declined → just adopt the view-only session from the original sign-in.
    public func declineEnroll() async {
        enrollOffer = nil
        guard let r = pendingResult else { return }
        pendingResult = nil
        await run { try await self.consume(r) }
    }

    public func selectFactor(_ f: BrokerFactor) async {
        guard let loginID else { return }
        await run {
            if self.webMode { try await self.broker.webSelectFactor(loginID: loginID, factorID: f.id) }
            else { try await self.broker.selectFactor(loginID: loginID, factorID: f.id) }
            self.factorSent = f
        }
    }

    public func verifyMfa(code: String) async {
        guard let loginID else { return }
        await run {
            let r: BrokerResult
            if self.webMode {
                r = try await self.broker.webVerify(loginID: loginID, code: code.trimmed, enroll: true)
            } else {
                r = try await self.broker.verifyMfa(loginID: loginID, code: code.trimmed, enroll: self.enrollConsent)
            }
            try await self.finishChurch(r)
        }
    }

    public func backFromMfa() { factorSent = nil }
    public func backToChurchStart() { resetChurch() }

    // MARK: - Church website (WebView capture — no password in our app)

    /// Open the in-app Church web sign-in.
    public func presentChurchWebLogin() { showChurchWebLogin = true }

    /// The WebView captured the Church session cookies (the leader signed in on the Church's own
    /// page). Post them to the broker, which verifies the session and mints ours. We adopt the
    /// view session directly (N2-guarded) — NOT the post-login enroll offer, which re-auths with a
    /// password we deliberately never collected here. Setting up daily sync is a separate, explicit
    /// step (the re-auth dialog's "Authorize on the Church website" button, enroll=true).
    public func churchWebLogin(cookies: [[String: String]]) async {
        showChurchWebLogin = false
        await run {
            let r = try await self.broker.captureSession(cookies: cookies, enroll: false)
            if r.authorized == false { throw BrokerError(SessionStore.noAccessMessage) }
            try await self.consume(r)
        }
    }

    // MARK: - Email code

    public func sendCode(email: String) async {
        guard !email.trimmed.isEmpty else { errorMessage = "Enter your email."; return }
        await run {
            if self.useRelay {
                try await self.broker.emailStart(email.trimmed)
            } else {
                try await self.auth.sendCode(email: email)
            }
            self.emailCodeSent = true
        }
    }

    public func verify(email: String, code: String) async {
        guard !code.trimmed.isEmpty else { errorMessage = "Enter the 6-digit code."; return }
        await run {
            if self.useRelay {
                let t = try await self.broker.emailVerify(email.trimmed, code.trimmed)
                let access = (t["access_token"] as? String) ?? ""
                let refresh = (t["refresh_token"] as? String) ?? ""
                try await self.auth.setSession(accessToken: access, refreshToken: refresh)
            } else {
                try await self.auth.verify(email: email, code: code)
            }
            // authStateChanges flips `phase` to .signedIn.
        }
    }

    public func enableRelay() {
        useRelay = true
        emailCodeSent = false
        errorMessage = nil
    }
    public func disableRelay() {
        useRelay = false
        emailCodeSent = false
        errorMessage = nil
    }

    // MARK: - Passkey

    public func passkeySignIn() async {
        await run {
            let r = try await self.passkeyLogin()
            try await self.consume(r)
        }
    }

    // MARK: - shared

    /// Turn a broker-minted OTP into a real Supabase session (port of `_consume`).
    /// N2: shown when a Church login succeeds but the calling has no covenant-path access.
    static let noAccessMessage =
        "This account doesn't have access to Covenant Path. Access is granted by your calling — "
        + "if you should have access, ask your stake leadership."

    private func consume(_ r: BrokerResult) async throws {
        guard let email = r.email, let otp = r.otp else {
            throw BrokerError("Sign-in service did not return a session.")
        }
        try await auth.consume(email: email, otp: otp)
    }

    public func signOut() async {
        await run { try await self.auth.signOut() }
    }

    /// Run an async action with busy/error bookkeeping (mirrors `login_page._run`).
    private func run(_ action: @escaping () async throws -> Void) async {
        isBusy = true
        errorMessage = nil
        statusMessage = nil
        do {
            try await action()
        } catch let e as BrokerError {
            errorMessage = e.message
        } catch {
            errorMessage = error.localizedDescription
        }
        isBusy = false
    }
}
