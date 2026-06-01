#if canImport(UIKit)
import SwiftUI

/// App entry point view. Three responsibilities, in order:
///   1. If Supabase isn't configured (empty URL/key), show a friendly "set the build config" screen
///      (mirrors the Flutter `_ConfigError`).
///   2. Otherwise build the service graph (one `SupabaseService` → auth + repository).
///   3. Switch between Login and Dashboard based on `SessionStore.phase`.
///
/// The iOS app target's `@main App` simply renders `RootView()` inside a `WindowGroup`.
public struct RootView: View {
    private let config: AppConfig

    public init(config: AppConfig = .current) {
        self.config = config
    }

    public var body: some View {
        if let service = SupabaseService.make(config: config) {
            ConfiguredRoot(service: service)
        } else {
            ConfigErrorView()
        }
    }
}

/// The configured app: owns the stores and routes by auth phase.
private struct ConfiguredRoot: View {
    @State private var session: SessionStore
    private let service: SupabaseService

    init(service: SupabaseService) {
        self.service = service
        _session = State(initialValue: SessionStore(
            auth: SupabaseAuthService(client: service.client)
        ))
    }

    var body: some View {
        Group {
            switch session.phase {
            case .loading:
                ProgressView().controlSize(.large)
            case .signedOut:
                LoginView()
            case .signedIn:
                DashboardView(
                    store: DashboardStore(
                        repo: SupabaseMembersRepository(client: service.client)
                    )
                )
            }
        }
        .environment(session)
        .task { session.start() }
    }
}

/// Shown when SUPABASE_URL / SUPABASE_ANON_KEY are missing from the build config.
struct ConfigErrorView: View {
    var body: some View {
        VStack(spacing: 16) {
            Image(systemName: "gearshape.2").font(.largeTitle).foregroundStyle(.secondary)
            Text("Configuration needed").font(.title3.bold())
            Text("""
            Missing SUPABASE_URL / SUPABASE_ANON_KEY.

            Set them in the app target's xcconfig (or Info.plist build settings) — see the README \
            "Configuration" section. The anon key is safe to ship; RLS does all access gating.
            """)
            .font(.callout)
            .foregroundStyle(.secondary)
            .multilineTextAlignment(.center)
        }
        .padding(32)
    }
}
#endif
