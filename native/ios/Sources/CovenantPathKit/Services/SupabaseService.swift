import Foundation
import Supabase

/// Thin singleton wrapper around the official `supabase-swift` SDK client. Everything that touches
/// the network (auth + Postgrest reads) goes through here so the rest of the app depends on small,
/// testable protocols rather than the SDK directly.
///
/// The client is created lazily from `AppConfig`. When the app isn't configured (empty URL/key),
/// `shared` is nil and the UI shows a configuration-needed screen.
public final class SupabaseService: @unchecked Sendable {

    public let client: SupabaseClient

    public init(config: AppConfig) {
        // Precondition is enforced by the caller (RootView only builds this when configured); we
        // force-unwrap the URL here because a SupabaseClient requires a non-optional URL.
        self.client = SupabaseClient(
            supabaseURL: config.supabaseURL!,
            supabaseKey: config.supabaseAnonKey
        )
    }

    /// Build the shared service if configured, else nil.
    public static func make(config: AppConfig = .current) -> SupabaseService? {
        guard config.isConfigured else { return nil }
        return SupabaseService(config: config)
    }
}
