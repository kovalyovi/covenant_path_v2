import Foundation
import Supabase
import Auth

/// Email-OTP authentication, the only login flow in the PoC (the Church-account broker + passkeys
/// are explicitly out of scope per the spec). Two steps, mirroring the Flutter `login_page.dart`:
///   1. `sendCode(email:)`  → `auth.signInWithOTP(email:)` → Supabase emails a 6-digit code.
///   2. `verify(email:code:)` → `auth.verifyOTP(email:token:type:.email)` → a live session.
/// RLS then scopes every query by the verified email.
public protocol AuthService: Sendable {
    /// The current session, if signed in.
    var currentSession: Session? { get async }
    /// An async stream of auth state changes (drives the root view's signed-in/out switch).
    var authStateChanges: AsyncStream<(event: AuthChangeEvent, session: Session?)> { get }

    func sendCode(email: String) async throws
    func verify(email: String, code: String) async throws
    func signOut() async throws

    // Broker-backed login support.
    /// The signed-in user's email (RLS scopes on this), or nil.
    var currentEmail: String? { get async }
    /// The signed-in user's access token (for broker calls), or "" when signed out.
    func accessToken() async -> String
    /// Turn a broker-minted OTP into a real Supabase session (Church/passkey login).
    func consume(email: String, otp: String) async throws
    /// Adopt broker-relayed tokens (email-relay backup path).
    func setSession(accessToken: String, refreshToken: String) async throws
}

public struct SupabaseAuthService: AuthService {
    private let client: SupabaseClient
    public init(client: SupabaseClient) { self.client = client }

    public var currentSession: Session? {
        get async { try? await client.auth.session }
    }

    public var authStateChanges: AsyncStream<(event: AuthChangeEvent, session: Session?)> {
        // `authStateChanges` is itself an AsyncStream in supabase-swift 2.x; re-expose it as a tuple
        // stream so the SwiftUI layer can `for await` without importing the SDK.
        AsyncStream { continuation in
            let task = Task {
                for await change in client.auth.authStateChanges {
                    continuation.yield((change.event, change.session))
                }
                continuation.finish()
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }

    public func sendCode(email: String) async throws {
        // `shouldCreateUser` defaults to true; the email must match an LCR-on-file address for RLS to
        // return any rows, but Supabase will still mint a session for any verified email.
        try await client.auth.signInWithOTP(email: email.trimmed)
    }

    public func verify(email: String, code: String) async throws {
        try await client.auth.verifyOTP(
            email: email.trimmed,
            token: code.trimmed,
            type: .email
        )
    }

    public func signOut() async throws {
        try await client.auth.signOut()
    }

    public var currentEmail: String? {
        get async { (try? await client.auth.session)?.user.email }
    }

    public func accessToken() async -> String {
        ((try? await client.auth.session)?.accessToken) ?? ""
    }

    public func consume(email: String, otp: String) async throws {
        try await client.auth.verifyOTP(email: email.trimmed, token: otp.trimmed, type: .email)
    }

    public func setSession(accessToken: String, refreshToken: String) async throws {
        try await client.auth.setSession(accessToken: accessToken, refreshToken: refreshToken)
    }
}

extension String {
    var trimmed: String { trimmingCharacters(in: .whitespacesAndNewlines) }
}
