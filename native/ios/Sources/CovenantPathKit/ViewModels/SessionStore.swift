import Foundation
import Observation
import Auth

/// App-wide auth state. Drives `RootView`'s switch between Login and the Dashboard. Uses the
/// Observation framework (`@Observable`) — views observe the `phase` and `isBusy`/`errorMessage`
/// fields directly.
@MainActor
@Observable
public final class SessionStore {

    public enum Phase: Equatable {
        case loading          // initial: checking for an existing session
        case signedOut
        case signedIn
    }

    public private(set) var phase: Phase = .loading
    public var isBusy = false
    public var errorMessage: String?
    /// True once a code has been sent and the UI should show the code field.
    public var codeSent = false

    private let auth: AuthService
    private var watchTask: Task<Void, Never>?

    public init(auth: AuthService) {
        self.auth = auth
    }

    /// Resolve the initial phase and start listening for auth changes.
    public func start() {
        Task { @MainActor in
            phase = (await auth.currentSession) != nil ? .signedIn : .signedOut
        }
        watchTask?.cancel()
        watchTask = Task { @MainActor [weak self] in
            guard let self else { return }
            for await change in auth.authStateChanges {
                // Any session presence flips the gate; sign-out clears it.
                switch change.event {
                case .signedIn, .tokenRefreshed, .userUpdated, .initialSession:
                    if change.session != nil { self.phase = .signedIn }
                case .signedOut:
                    self.phase = .signedOut
                    self.codeSent = false
                default:
                    break
                }
            }
        }
    }

    // MARK: - email OTP

    public func sendCode(email: String) async {
        guard !email.trimmed.isEmpty else { errorMessage = "Enter your email."; return }
        await run {
            try await self.auth.sendCode(email: email)
            self.codeSent = true
        }
    }

    public func verify(email: String, code: String) async {
        guard !code.trimmed.isEmpty else { errorMessage = "Enter the 6-digit code."; return }
        await run {
            try await self.auth.verify(email: email, code: code)
            // The authStateChanges stream flips `phase` to .signedIn; nothing else to do here.
        }
    }

    public func resetEmailEntry() {
        codeSent = false
        errorMessage = nil
    }

    public func signOut() async {
        await run { try await self.auth.signOut() }
    }

    /// Run an async action with busy/error bookkeeping (mirrors `login_page._run`).
    private func run(_ action: @escaping () async throws -> Void) async {
        isBusy = true
        errorMessage = nil
        do {
            try await action()
        } catch {
            errorMessage = Self.friendly(error)
        }
        isBusy = false
    }

    /// `AuthError` (and most SDK errors) conform to `LocalizedError`, so `localizedDescription`
    /// already yields a readable message; this hook is where richer mapping would go if needed.
    static func friendly(_ error: Error) -> String {
        error.localizedDescription
    }
}
