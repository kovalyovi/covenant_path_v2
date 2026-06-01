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

    public var isConfigured: Bool {
        supabaseURL != nil && !supabaseAnonKey.isEmpty
    }

    /// Build from a plist dictionary (the app target passes `Bundle.main.infoDictionary`). Tests can
    /// inject their own values directly via `init(url:anonKey:)`.
    public init(infoDictionary: [String: Any]?) {
        let urlString = (infoDictionary?["SUPABASE_URL"] as? String)?
            .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        let key = (infoDictionary?["SUPABASE_ANON_KEY"] as? String)?
            .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        self.supabaseURL = urlString.isEmpty ? nil : URL(string: urlString)
        self.supabaseAnonKey = key
    }

    public init(url: URL?, anonKey: String) {
        self.supabaseURL = url
        self.supabaseAnonKey = anonKey
    }

    /// The live configuration read from the main bundle.
    public static let current = AppConfig(infoDictionary: Bundle.main.infoDictionary)
}
