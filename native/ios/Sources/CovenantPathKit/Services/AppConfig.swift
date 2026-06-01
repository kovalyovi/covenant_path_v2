import Foundation

/// Build-time configuration. The Supabase URL + anon key are NOT hardcoded — they're read from the
/// app bundle's Info.plist keys `SUPABASE_URL` / `SUPABASE_ANON_KEY`, which in turn come from an
/// xcconfig build setting (see README "Configuration"). The anon/publishable key is safe on clients
/// (RLS does all gating); we still keep it out of source control via xcconfig.
///
/// Defaults are empty strings; an empty config surfaces a friendly "not configured" screen rather
/// than crashing, mirroring the Flutter app's `_ConfigError`.
public struct AppConfig: Sendable {
    public let supabaseURL: URL?
    public let supabaseAnonKey: String
    /// Church-login auth broker base URL (backend/auth_broker). Empty => only Email-code login is
    /// shown and broker-backed features (Church/passkey login, sync settings, report, admin) hide.
    public let brokerURL: String

    public var isConfigured: Bool {
        supabaseURL != nil && !supabaseAnonKey.isEmpty
    }

    /// Whether broker-backed features are available (mirrors the Flutter `brokerUrl.isNotEmpty`).
    public var hasBroker: Bool { !brokerURL.isEmpty }

    /// Build from a plist dictionary (the app target passes `Bundle.main.infoDictionary`). Tests can
    /// inject their own values directly via `init(url:anonKey:brokerURL:)`.
    public init(infoDictionary: [String: Any]?) {
        let urlString = (infoDictionary?["SUPABASE_URL"] as? String)?
            .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        let key = (infoDictionary?["SUPABASE_ANON_KEY"] as? String)?
            .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        let broker = (infoDictionary?["BROKER_URL"] as? String)?
            .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        self.supabaseURL = urlString.isEmpty ? nil : URL(string: urlString)
        self.supabaseAnonKey = key
        // Drop a trailing slash so "$base$path" never doubles up.
        self.brokerURL = broker.hasSuffix("/") ? String(broker.dropLast()) : broker
    }

    public init(url: URL?, anonKey: String, brokerURL: String = "") {
        self.supabaseURL = url
        self.supabaseAnonKey = anonKey
        let b = brokerURL.trimmingCharacters(in: .whitespacesAndNewlines)
        self.brokerURL = b.hasSuffix("/") ? String(b.dropLast()) : b
    }

    /// The live configuration read from the main bundle.
    public static let current = AppConfig(infoDictionary: Bundle.main.infoDictionary)
}
