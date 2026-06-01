#if canImport(AuthenticationServices) && canImport(UIKit)
import Foundation
import AuthenticationServices
import UIKit

/// Native passkey (WebAuthn) login + registration against the broker's `/webauthn/*` routes, using
/// the platform `AuthenticationServices` (ASAuthorization) APIs — the native analog of
/// `passkey_client.dart` (which uses the browser WebAuthn API on web).
///
/// IMPORTANT (documented partial): platform passkeys require an **associated-domains** entitlement
/// (`webcredentials:<rp-id>`) tying the app to the broker's domain, plus a server-published AASA
/// file. That can't be provisioned in the unsigned CI build, so `available` is gated behind a
/// `PASSKEY_RP_ID` Info.plist value (empty by default). When unset, the Login screen shows the
/// passkey button disabled with a "use email code on this device" note. When a real build sets
/// `PASSKEY_RP_ID` + the entitlement, the full ASAuthorization flow below runs end-to-end.
public final class PasskeyService: NSObject, @unchecked Sendable {
    private let broker: BrokerService
    private let rpID: String

    public init(broker: BrokerService, rpID: String) {
        self.broker = broker
        self.rpID = rpID
    }

    /// Available only when broker + an RP id are configured AND the OS supports platform passkeys.
    public var available: Bool {
        guard broker.available, !rpID.isEmpty else { return false }
        if #available(iOS 16.0, *) { return true }
        return false
    }

    // MARK: - login (unauthenticated)

    /// Passwordless login → a verifiable Supabase session ({email, otp}) to consume. Port of `login`.
    @available(iOS 16.0, *)
    public func login() async throws -> BrokerResult {
        let begin = try await broker.postJSON("/webauthn/login/begin", [:])
        guard let handle = begin["handle"],
              let options = begin["options"] as? [String: Any] else {
            throw BrokerError("Passkey service did not return a challenge.")
        }
        let assertion = try await performAssertion(options: options)
        let done = try await broker.postJSON("/webauthn/login/complete", [
            "handle": handle,
            "credential": assertion,
        ])
        let session = (done["session"] as? [String: Any]) ?? [:]
        return BrokerResult(email: session["email"] as? String, otp: session["otp"] as? String)
    }

    // MARK: - register (requires a current session — caller ensures it)

    /// Register a passkey for the signed-in user. Port of `register` (broker calls are authed).
    @available(iOS 16.0, *)
    public func register() async throws {
        let begin = try await broker.authed("POST", "/webauthn/register/begin")
        guard let handle = begin["handle"],
              let options = begin["options"] as? [String: Any] else {
            throw BrokerError("Passkey service did not return a registration challenge.")
        }
        let attestation = try await performRegistration(options: options)
        _ = try await broker.authed("POST", "/webauthn/register/complete", body: [
            "handle": handle,
            "credential": attestation,
        ])
    }

    // MARK: - ASAuthorization plumbing

    @available(iOS 16.0, *)
    private func performAssertion(options: [String: Any]) async throws -> [String: Any] {
        let challenge = try base64urlData(options["challenge"])
        let provider = ASAuthorizationPlatformPublicKeyCredentialProvider(relyingPartyIdentifier: rpID)
        let request = provider.createCredentialAssertionRequest(challenge: challenge)
        if let allow = options["allowCredentials"] as? [[String: Any]] {
            request.allowedCredentials = allow.compactMap { c in
                (try? base64urlData(c["id"])).map {
                    ASAuthorizationPlatformPublicKeyCredentialDescriptor(credentialID: $0)
                }
            }
        }
        let cred = try await run(request)
        guard let assertion = cred as? ASAuthorizationPlatformPublicKeyCredentialAssertion else {
            throw BrokerError("Unexpected passkey assertion type.")
        }
        return [
            "id": b64url(assertion.credentialID),
            "rawId": b64url(assertion.credentialID),
            "type": "public-key",
            "response": [
                "clientDataJSON": b64url(assertion.rawClientDataJSON),
                "authenticatorData": b64url(assertion.rawAuthenticatorData),
                "signature": b64url(assertion.signature),
                "userHandle": assertion.userID.map(b64url) as Any,
            ],
        ]
    }

    @available(iOS 16.0, *)
    private func performRegistration(options: [String: Any]) async throws -> [String: Any] {
        let challenge = try base64urlData(options["challenge"])
        let user = (options["user"] as? [String: Any]) ?? [:]
        let userID = try base64urlData(user["id"])
        let name = (user["name"] as? String) ?? ""
        let provider = ASAuthorizationPlatformPublicKeyCredentialProvider(relyingPartyIdentifier: rpID)
        let request = provider.createCredentialRegistrationRequest(
            challenge: challenge, name: name, userID: userID)
        let cred = try await run(request)
        guard let reg = cred as? ASAuthorizationPlatformPublicKeyCredentialRegistration else {
            throw BrokerError("Unexpected passkey registration type.")
        }
        return [
            "id": b64url(reg.credentialID),
            "rawId": b64url(reg.credentialID),
            "type": "public-key",
            "response": [
                "clientDataJSON": b64url(reg.rawClientDataJSON),
                "attestationObject": b64url(reg.rawAttestationObject ?? Data()),
            ],
        ]
    }

    // Strong refs kept alive for the duration of one ASAuthorization flow (the controller's
    // delegate/presentationContextProvider are weak, so we must retain both ourselves).
    private var activeController: AnyObject?
    private var activeDelegate: AnyObject?

    // Bridge ASAuthorizationController's delegate callbacks into async/await.
    @available(iOS 16.0, *)
    @MainActor
    private func run(_ request: ASAuthorizationRequest) async throws -> ASAuthorizationCredential {
        try await withCheckedThrowingContinuation { cont in
            let controller = ASAuthorizationController(authorizationRequests: [request])
            let delegate = AuthDelegate { [weak self] result in
                // Release the retained refs once the flow completes.
                self?.activeController = nil
                self?.activeDelegate = nil
                cont.resume(with: result)
            }
            controller.delegate = delegate
            controller.presentationContextProvider = delegate
            self.activeController = controller
            self.activeDelegate = delegate
            controller.performRequests()
        }
    }

    // MARK: - base64url helpers (WebAuthn JSON encodes binary as base64url, no padding)

    private func base64urlData(_ value: Any?) throws -> Data {
        guard let s = value as? String, let d = Data(base64urlEncoded: s) else {
            throw BrokerError("Malformed passkey challenge.")
        }
        return d
    }
    private func b64url(_ d: Data) -> String { d.base64urlEncodedString() }
}

@available(iOS 16.0, *)
private final class AuthDelegate: NSObject, ASAuthorizationControllerDelegate,
                                  ASAuthorizationControllerPresentationContextProviding {
    private let completion: (Result<ASAuthorizationCredential, Error>) -> Void
    init(_ completion: @escaping (Result<ASAuthorizationCredential, Error>) -> Void) {
        self.completion = completion
    }

    func authorizationController(controller: ASAuthorizationController,
                                 didCompleteWithAuthorization authorization: ASAuthorization) {
        completion(.success(authorization.credential))
    }
    func authorizationController(controller: ASAuthorizationController,
                                 didCompleteWithError error: Error) {
        completion(.failure(error))
    }
    func presentationAnchor(for controller: ASAuthorizationController) -> ASPresentationAnchor {
        // Best-effort: the foreground window scene's key window.
        let scenes = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }
        let window = scenes.flatMap { $0.windows }.first { $0.isKeyWindow }
        return window ?? ASPresentationAnchor()
    }
}

// MARK: - base64url <-> Data

extension Data {
    init?(base64urlEncoded s: String) {
        var b64 = s.replacingOccurrences(of: "-", with: "+").replacingOccurrences(of: "_", with: "/")
        while b64.count % 4 != 0 { b64.append("=") }
        guard let d = Data(base64Encoded: b64) else { return nil }
        self = d
    }
    func base64urlEncodedString() -> String {
        base64EncodedString()
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
    }
}
#endif
