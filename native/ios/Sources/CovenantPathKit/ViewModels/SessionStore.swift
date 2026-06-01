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

    // Email-code flow state.
    public var emailCodeSent = false
    public var useRelay = false   // route email-code through the broker (blocked networks)

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

    public func churchSignIn(username: String, password: String) async {
        await run {
            let r = try await self.broker.password(username.trimmed, password, enroll: true)
            if r.mfaRequired {
                self.loginID = r.loginID
                self.factors = r.factors
                // Auto-send if there's exactly one factor (matches Flutter).
                if r.factors.count == 1 { await self.selectFactor(r.factors[0]) }
                return
            }
            try await self.consume(r)
        }
    }

    public func selectFactor(_ f: BrokerFactor) async {
        guard let loginID else { return }
        await run {
            try await self.broker.selectFactor(loginID: loginID, factorID: f.id)
            self.factorSent = f
        }
    }

    public func verifyMfa(code: String) async {
        guard let loginID else { return }
        await run {
            let r = try await self.broker.verifyMfa(loginID: loginID, code: code.trimmed, enroll: true)
            try await self.consume(r)
        }
    }

    public func backFromMfa() { factorSent = nil }
    public func backToChurchStart() { resetChurch() }

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
