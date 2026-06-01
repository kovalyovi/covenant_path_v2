import Foundation
import Supabase

/// The configured service graph, built once at app start from `AppConfig`. Bundles the Supabase
/// client wrappers plus the broker/passkey services so the view layer injects ONE object instead of
/// wiring each dependency by hand. Mirrors how the Flutter app reaches `supabase`, `BrokerClient`,
/// `AdminClient`, `PasskeyClient` ad hoc — here they're owned in one place.
public final class AppServices: @unchecked Sendable {
    public let config: AppConfig
    public let supabase: SupabaseService
    public let auth: AuthService
    public let members: MembersRepository
    public let gateway: SupabaseGateway
    public let broker: BrokerService

    public init(config: AppConfig, supabase: SupabaseService) {
        self.config = config
        self.supabase = supabase
        let client = supabase.client
        let authService = SupabaseAuthService(client: client)
        self.auth = authService
        self.members = SupabaseMembersRepository(client: client)
        self.gateway = SupabaseGatewayImpl(client: client)
        // Broker calls carry the live Supabase access token.
        self.broker = BrokerService(baseURL: config.brokerURL) {
            await authService.accessToken()
        }
    }

    /// Build the graph if Supabase is configured, else nil (the UI shows a config-needed screen).
    public static func make(config: AppConfig = .current) -> AppServices? {
        guard let supabase = SupabaseService.make(config: config) else { return nil }
        return AppServices(config: config, supabase: supabase)
    }

    /// The passkey RP id from the build config (empty => passkey disabled with a note). Read here so
    /// `PasskeyService` stays free of bundle lookups.
    public var passkeyRPID: String {
        (Bundle.main.infoDictionary?["PASSKEY_RP_ID"] as? String)?
            .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
    }
}
