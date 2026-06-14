import Foundation

/// Faithful port of `apps/viewer/lib/broker_client.dart` + `admin_client.dart`. The Church's Okta
/// can't be reached directly from a client (CORS / mobile constraints); the broker authenticates
/// server-side and hands back a Supabase OTP the app verifies. Everything here is plain `URLSession`
/// (no SDK), so the whole service stays in the cross-platform `CovenantPathKit` module.
///
/// `available` mirrors `brokerUrl.isNotEmpty`. Authed calls carry the signed-in Supabase access
/// token via the injected `tokenProvider` (the app wires it to the Supabase session).

public struct BrokerError: Error, LocalizedError, Sendable {
    public let message: String
    public init(_ message: String) { self.message = message }
    public var errorDescription: String? { message }
}

/// One MFA factor offered by Okta (e.g. "Text message to •••1234"). Port of `BrokerFactor`.
public struct BrokerFactor: Identifiable, Sendable, Hashable {
    public let id: String
    public let label: String
    public let method: String
    init(json: [String: Any]) {
        id = (json["id"] as? String) ?? ""
        label = (json["label"] as? String) ?? (json["method"] as? String) ?? "Code"
        method = (json["method"] as? String) ?? ""
    }
}

/// Result of a login step: either a verifiable Supabase session, or an MFA challenge. Port of
/// `BrokerResult`.
public struct BrokerResult: Sendable {
    public let email: String?
    public let otp: String?
    public let loginID: String?
    public let factors: [BrokerFactor]
    public let name: String?
    /// N2: covenant-path access from the broker enroll step. nil = unknown (don't block);
    /// false = no access → block at login.
    public let authorized: Bool?
    /// #8: the stake already has an INSUFFICIENT credential this session would improve.
    public let canImprove: Bool
    /// #8: the stake has NO usable credential yet and this authorized leader could set one up.
    public let canEnroll: Bool
    public let stake: String?
    public let missing: [String]
    /// True when an enroll=true login actually stored/refreshed the sync credential (drives the
    /// re-auth success toast, mirrors web `BrokerResult.stored`).
    public let stored: Bool
    /// This session is a WARD/BRANCH-level leader's — enrollment is refused (a ward leader sees their
    /// unit via their role; daily sync is set up per stake). `enrollBlockReason` carries the message.
    /// Green Level Ward incident, 2026-06-13.
    public let wardScoped: Bool
    public let enrollBlockReason: String?
    /// The stake already has a credential and THIS session is strictly weaker — re-authorizing with it
    /// would reduce coverage (R4). `existingProvider` names who currently provides the sync.
    public let wouldDowngrade: Bool
    public let existingProvider: String?
    public init(email: String? = nil, otp: String? = nil, loginID: String? = nil,
                factors: [BrokerFactor] = [], name: String? = nil, authorized: Bool? = nil,
                canImprove: Bool = false, canEnroll: Bool = false, stake: String? = nil,
                missing: [String] = [], stored: Bool = false, wardScoped: Bool = false,
                enrollBlockReason: String? = nil, wouldDowngrade: Bool = false,
                existingProvider: String? = nil) {
        self.email = email; self.otp = otp; self.loginID = loginID
        self.factors = factors; self.name = name; self.authorized = authorized
        self.canImprove = canImprove; self.canEnroll = canEnroll; self.stake = stake; self.missing = missing
        self.stored = stored
        self.wardScoped = wardScoped; self.enrollBlockReason = enrollBlockReason
        self.wouldDowngrade = wouldDowngrade; self.existingProvider = existingProvider
    }
    public var mfaRequired: Bool { loginID != nil && otp == nil }
}

/// Credential info from /auth/enrollment-status (port of `CredentialInfo`).
public struct CredentialInfo: Sendable {
    public let state: String          // "none" | "active" | "stale" | "revoked"
    public let complete: Bool
    public let principalName: String?
    public let isProvider: Bool
    public let enrolledAt: String?
    /// When state == "stale", the last sync error (e.g. "SSO did not complete…").
    public let lastError: String?
    /// This calling can read the per-member LCR profile that carries the patriarchal-blessing flag —
    /// so re-authorizing with it would refresh that one field (the daily Member Tools sync can't).
    /// Drives the patriarchal-refresh banner alongside `isProvider` + `EnrollmentStatus.patriarchalPending`.
    public let canRefreshPatriarchal: Bool
    public var isActive: Bool { state == "active" }
    /// Stale = the delegated Church session died → daily sync is failing until re-authorized.
    public var isStale: Bool { state == "stale" }
    public var isRevoked: Bool { state == "revoked" }
    public var isNone: Bool { state == "none" }
    init(json: [String: Any]) {
        state = (json["state"] as? String) ?? "none"
        complete = (json["complete"] as? Bool) ?? false
        principalName = json["principal_name"] as? String
        isProvider = (json["is_provider"] as? Bool) ?? false
        enrolledAt = json["enrolled_at"] as? String
        lastError = json["last_error"] as? String
        canRefreshPatriarchal = (json["can_refresh_patriarchal"] as? Bool) ?? false
    }
}

/// Response from /auth/enrollment-status (port of `EnrollmentStatus`).
public struct EnrollmentStatus: Sendable {
    public let stakeName: String?
    public let stakeID: String?
    /// LCR stake unit number — the stable ID shown to users (stakes get renamed).
    public let unitNumber: Int?
    public let lastSyncedAt: String?
    public let memberCount: Int
    public let hasData: Bool
    public let noRole: Bool
    /// Real, baptized members in this stake still missing the profile-only patriarchal-blessing flag —
    /// the count the patriarchal-refresh banner shows. 0 hides the banner.
    public let patriarchalPending: Int
    public let credential: CredentialInfo
    init(json: [String: Any]) {
        stakeName = json["stake_name"] as? String
        stakeID = json["stake_id"] as? String
        unitNumber = (json["unit_number"] as? NSNumber)?.intValue
        lastSyncedAt = json["last_synced_at"] as? String
        memberCount = (json["member_count"] as? NSNumber)?.intValue ?? 0
        hasData = (json["has_data"] as? Bool) ?? false
        noRole = (json["status"] as? String) == "no_role"
        patriarchalPending = (json["patriarchal_pending"] as? NSNumber)?.intValue ?? 0
        credential = CredentialInfo(json: (json["credential"] as? [String: Any]) ?? [:])
    }
}

public final class BrokerService: @unchecked Sendable {
    public let baseURL: String
    /// Returns the current Supabase access token (empty if signed out). Injected by the app.
    private let tokenProvider: @Sendable () async -> String
    /// Optional status callback for the cold-start "waking up the sign-in service" line.
    public var onStatus: (@Sendable (String) -> Void)?

    public init(baseURL: String, tokenProvider: @escaping @Sendable () async -> String) {
        self.baseURL = baseURL
        self.tokenProvider = tokenProvider
    }

    public var available: Bool { !baseURL.isEmpty }

    /// N5: wake the free-tier broker early (cheap /health GET) so it's warm by the time the user
    /// submits credentials, hiding the ~60s cold start. Best-effort; errors ignored.
    public func warmUp() async {
        guard available, let u = URL(string: baseURL + "/health") else { return }
        _ = try? await URLSession.shared.data(from: u)
    }

    // Render free hosting sleeps when idle; the first request after a sleep can fail to connect.
    // Retry across ~63s so a cold start resolves itself (delays sum like the Flutter client).
    private static let retryDelays: [UInt64] = [3, 6, 9, 12, 15, 18].map { $0 * 1_000_000_000 }

    // MARK: - low-level

    private func url(_ path: String) throws -> URL {
        guard available, let u = URL(string: baseURL + path) else {
            throw BrokerError("Church login is not configured (BROKER_URL).")
        }
        return u
    }

    /// POST with cold-start retry; returns the decoded JSON object. Port of `_postJson`.
    @discardableResult
    public func postJSON(_ path: String, _ body: [String: Any]) async throws -> [String: Any] {
        let u = try url(path)
        var lastErr: Error?
        var data: Data?
        var status = 0
        for attempt in 0...Self.retryDelays.count {
            do {
                // 95s, not 30: a FIRST-ENROLL login runs the broker's access evaluation server-side
                // (30-60s legitimately). A 30s abort dropped the response after the broker succeeded,
                // so the authorize-sync offer never appeared (mirrors the web client fix).
                var req = URLRequest(url: u, timeoutInterval: 95)
                req.httpMethod = "POST"
                req.setValue("application/json", forHTTPHeaderField: "Content-Type")
                req.httpBody = try JSONSerialization.data(withJSONObject: body)
                let (d, resp) = try await URLSession.shared.data(for: req)
                data = d
                status = (resp as? HTTPURLResponse)?.statusCode ?? 0
                break
            } catch {
                lastErr = error
                if attempt < Self.retryDelays.count {
                    onStatus?("Waking up the sign-in service… this can take up to a minute on first use.")
                    try? await Task.sleep(nanoseconds: Self.retryDelays[attempt])
                }
            }
        }
        guard let data else {
            throw BrokerError("Could not reach the sign-in service after several tries. It may be "
                + "starting up — please try again in a minute. (\(lastErr?.localizedDescription ?? "?"))")
        }
        return try Self.decode(data, status: status, fallback: "Sign-in failed (\(status)).")
    }

    private func tokenOrThrow() async throws -> String {
        let token = await tokenProvider()
        if token.isEmpty { throw BrokerError("Not signed in.") }
        return token
    }

    /// Shared authed request carrying the signed-in user's Supabase token. Port of `_authed`.
    @discardableResult
    public func authed(_ method: String, _ path: String, body: [String: Any]? = nil) async throws -> [String: Any] {
        let u = try url(path)
        let token = try await tokenOrThrow()
        var req = URLRequest(url: u, timeoutInterval: 40)
        req.httpMethod = method
        req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if method != "GET" {
            req.httpBody = try JSONSerialization.data(withJSONObject: body ?? [:])
        }
        let (data, resp) = try await URLSession.shared.data(for: req)
        let status = (resp as? HTTPURLResponse)?.statusCode ?? 0
        if status == 403 { throw BrokerError("Not authorized (admins only).") }
        return try Self.decode(data, status: status, fallback: "Request failed (\(status)).")
    }

    static func decode(_ data: Data, status: Int, fallback: String) throws -> [String: Any] {
        var obj: [String: Any] = [:]
        if !data.isEmpty {
            if let parsed = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] {
                obj = parsed
            } else if status >= 400 {
                throw BrokerError(fallback)
            }
        }
        if status >= 400 {
            let detail = (obj["detail"] as? String) ?? fallback
            throw BrokerError(detail)
        }
        return obj
    }

    private func result(from data: [String: Any]) -> BrokerResult {
        if (data["status"] as? String) == "mfa_required" {
            let factors = ((data["factors"] as? [[String: Any]]) ?? []).map(BrokerFactor.init(json:))
            return BrokerResult(loginID: data["login_id"] as? String, factors: factors)
        }
        let session = (data["session"] as? [String: Any]) ?? [:]
        let enroll = data["enroll"] as? [String: Any]
        return BrokerResult(email: session["email"] as? String,
                            otp: session["otp"] as? String,
                            name: data["identity_name"] as? String,
                            // N2: only an explicit false blocks; absent/errored enroll → nil.
                            authorized: enroll?["authorized"] as? Bool,
                            canImprove: (enroll?["can_improve"] as? Bool) ?? false,
                            canEnroll: (enroll?["can_enroll"] as? Bool) ?? false,
                            stake: enroll?["stake"] as? String,
                            missing: (enroll?["missing"] as? [Any])?.compactMap { $0 as? String } ?? [],
                            stored: (enroll?["stored"] as? Bool) == true,
                            wardScoped: (enroll?["ward_scoped"] as? Bool) == true,
                            enrollBlockReason: enroll?["enroll_block_reason"] as? String,
                            wouldDowngrade: (enroll?["would_downgrade"] as? Bool) == true,
                            existingProvider: enroll?["existing_provider"] as? String)
    }

    // MARK: - Church account login (port of password/selectFactor/verifyMfa)

    public func password(_ username: String, _ password: String, enroll: Bool = false) async throws -> BrokerResult {
        let d = try await postJSON("/auth/password", ["username": username, "password": password, "enroll": enroll])
        return result(from: d)
    }

    /// Captured-session lane: the leader signed in on the Church's OWN web page inside a WKWebView
    /// (password autofilled/typed on churchofjesuschrist.org — never in our UI or on our server),
    /// and we post the resulting Church session cookies here. The broker verifies the session and
    /// returns the same shape as the password lane (a Supabase session for login, or the enroll
    /// result). `cookies` are {name, value, domain, path} dicts captured from the WebView.
    public func captureSession(cookies: [[String: String]], enroll: Bool = false) async throws -> BrokerResult {
        let d = try await postJSON("/auth/session", ["cookies": cookies, "enroll": enroll])
        return result(from: d)
    }

    public func selectFactor(loginID: String, factorID: String) async throws {
        _ = try await postJSON("/auth/mfa/select", ["login_id": loginID, "factor_id": factorID])
    }

    public func verifyMfa(loginID: String, code: String, enroll: Bool = false) async throws -> BrokerResult {
        let d = try await postJSON("/auth/mfa/verify", ["login_id": loginID, "code": code, "enroll": enroll])
        return result(from: d)
    }

    // Credential-capture (one-MFA) lane: authn → LCR authorize → MFA so a SINGLE MFA mints the 45-day
    // Member Tools sync token (server-side, persisted at enroll). Used by the ENROLL / re-auth so a
    // typed-password enrollment yields unattended 45-day sync without storing the password or a TOTP.
    public func webStart(_ username: String, _ password: String, enroll: Bool = true) async throws -> BrokerResult {
        let d = try await postJSON("/auth/web/start", ["username": username, "password": password, "enroll": enroll])
        return result(from: d)
    }

    public func webSelectFactor(loginID: String, factorID: String) async throws {
        _ = try await postJSON("/auth/web/select", ["login_id": loginID, "factor_id": factorID])
    }

    public func webVerify(loginID: String, code: String, enroll: Bool = true) async throws -> BrokerResult {
        let d = try await postJSON("/auth/web/verify", ["login_id": loginID, "code": code, "enroll": enroll])
        return result(from: d)
    }

    // NOTE: the passwordless Church-login lane (Okta emailed code, /auth/otp/*) was REMOVED
    // 2026-06-12 — its app-scoped Okta session could never mint the 45-day daily-sync token.
    // Church auth is now username+password only (password()/webStart()). Passwordless VIEWING uses
    // the Supabase email relay below. See docs/DECISIONS.md (ADR-011).

    // MARK: - email relay (port of emailStart/emailVerify)

    public func emailStart(_ email: String) async throws {
        _ = try await postJSON("/auth/email/start", ["email": email])
    }

    public func emailVerify(_ email: String, _ code: String) async throws -> [String: Any] {
        try await postJSON("/auth/email/verify", ["email": email, "code": code])
    }

    // MARK: - enrollment / sync / schedule / drive (authed)

    public func enrollmentStatus() async throws -> EnrollmentStatus {
        EnrollmentStatus(json: try await authed("GET", "/auth/enrollment-status"))
    }

    public func revoke(stakeID: String) async throws {
        _ = try await authed("POST", "/auth/revoke", body: ["stake_id": stakeID])
    }

    @discardableResult
    public func syncNow() async throws -> [String: Any] {
        try await authed("POST", "/auth/sync-now")
    }

    public func getSchedule() async throws -> [String: Any] { try await authed("GET", "/auth/schedule") }
    public func setSchedule(hourET: Int, paused: Bool) async throws -> [String: Any] {
        try await authed("POST", "/auth/schedule", body: ["hour_et": hourET, "paused": paused])
    }

    public func googleDriveStatus() async throws -> [String: Any] { try await authed("GET", "/auth/google/status") }
    public func googleDriveStart() async throws -> [String: Any] { try await authed("POST", "/auth/google/start") }
    public func googleDriveDisconnect() async throws -> [String: Any] { try await authed("POST", "/auth/google/disconnect") }

    // MARK: - contact / report (authed)

    public func contact(subject: String, message: String) async throws {
        _ = try await authed("POST", "/contact", body: ["subject": subject, "message": message])
    }

    public func report() async throws -> [String: Any] { try await authed("GET", "/report") }

    @discardableResult
    public func emailReport(toEmail: String? = nil) async throws -> [String: Any] {
        var body: [String: Any] = [:]
        if let toEmail, !toEmail.isEmpty { body["to_email"] = toEmail }
        return try await authed("POST", "/report/email", body: body)
    }

    // MARK: - feedback (admin_client port; available to all signed-in users → GitHub issue)

    public func feedback(title: String, body: String) async throws -> [String: Any] {
        try await authed("POST", "/feedback", body: ["title": title, "body": body])
    }

    // MARK: - admin/ops (port of admin_client.dart)

    public func adminSummary() async throws -> [String: Any] { try await authed("GET", "/admin/summary") }
    public func adminActions() async throws -> [String: Any] { try await authed("GET", "/admin/actions") }
    public func adminDiagnostics() async throws -> [String: Any] { try await authed("GET", "/admin/diagnostics") }
    public func adminEnrolledStakes() async throws -> [String: Any] { try await authed("GET", "/admin/enrolled-stakes") }
    public func adminRevokeStake(_ stakeID: String) async throws -> [String: Any] {
        try await authed("POST", "/admin/stakes/\(stakeID)/revoke")
    }
    /// Wipe a stake's member data (keeps the stake + roles + credential; repopulates next sync).
    public func adminWipeStakeData(_ stakeID: String) async throws -> [String: Any] {
        try await authed("POST", "/admin/stakes/\(stakeID)/wipe-data")
    }
    /// Remove a stake completely (credential + members + roles + the stake row). Irreversible.
    public func adminRemoveStake(_ stakeID: String) async throws -> [String: Any] {
        try await authed("POST", "/admin/stakes/\(stakeID)/remove")
    }
    public func adminRun(_ workflow: String, inputs: [String: Any]? = nil) async throws -> [String: Any] {
        var body: [String: Any] = ["workflow": workflow]
        if let inputs { body["inputs"] = inputs }
        return try await authed("POST", "/admin/actions/run", body: body)
    }
    public func adminRerun(_ runID: Int) async throws -> [String: Any] {
        try await authed("POST", "/admin/actions/\(runID)/rerun")
    }
    public func adminInvite(_ email: String) async throws -> [String: Any] {
        try await authed("POST", "/admin/invite", body: ["email": email])
    }

    // MARK: - error telemetry (port of error_reporter.dart → /log; best-effort, never throws)

    public func log(type: String, message: String, surface: String, where loc: String?) {
        guard available, let u = URL(string: baseURL + "/log") else { return }
        let trimmed = message.count > 400 ? String(message.prefix(400)) : message
        var context: [String: Any] = ["type": type]
        if let loc { context["where"] = loc }
        let body: [String: Any] = [
            "level": "error", "event": "client.error", "surface": surface,
            "message": trimmed, "context": context,
        ]
        guard let data = try? JSONSerialization.data(withJSONObject: body) else { return }
        var req = URLRequest(url: u, timeoutInterval: 10)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = data
        // Fire-and-forget; telemetry must never surface an error.
        Task { _ = try? await URLSession.shared.data(for: req) }
    }

    /// Ship a performance summary to `/log` (event=client.perf). PII-free (metric + ms only), so it is
    /// NOT scrubbed. Pull via `python tools/render_logs.py --text PERF`. Fire-and-forget. See `Perf`.
    public func logPerf(summary: String, context: [String: Any]) {
        guard available, let u = URL(string: baseURL + "/log") else { return }
        var ctx = context
        ctx["kind"] = "perf"
        let body: [String: Any] = [
            "level": "info", "event": "client.perf", "surface": "ios",
            "message": String(summary.prefix(400)), "context": ctx,
        ]
        guard let data = try? JSONSerialization.data(withJSONObject: body) else { return }
        var req = URLRequest(url: u, timeoutInterval: 10)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = data
        Task { _ = try? await URLSession.shared.data(for: req) }
    }
}
