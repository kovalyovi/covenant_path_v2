#if canImport(UIKit)
import SwiftUI

/// App entry point view. Responsibilities, in order:
///   1. If Supabase isn't configured (empty URL/key), show a friendly "set the build config" screen
///      (mirrors the Flutter `_ConfigError`).
///   2. Otherwise build the service graph (`AppServices`) and install error reporting → broker /log.
///   3. Switch between Login and (biometric-gated) Dashboard based on `SessionStore.phase`.
///   4. Apply the persisted light/dark theme app-wide.
public struct RootView: View {
    private let config: AppConfig

    public init(config: AppConfig = .current) {
        self.config = config
    }

    public var body: some View {
        if let services = AppServices.make(config: config) {
            ConfiguredRoot(services: services)
        } else {
            ConfigErrorView()
        }
    }
}

/// The configured app: owns the stores + theme and routes by auth phase.
private struct ConfiguredRoot: View {
    @State private var session: SessionStore
    @State private var theme = ThemeController()
    private let services: AppServices

    init(services: AppServices) {
        self.services = services
        let passkey = PasskeyService(broker: services.broker, rpID: services.passkeyRPID)
        _session = State(initialValue: SessionStore(
            auth: services.auth,
            broker: services.broker,
            passkeyAvailable: { passkey.available },
            passkeyLogin: {
                if #available(iOS 16.0, *) { return try await passkey.login() }
                throw BrokerError("Passkeys need iOS 16 or later.")
            }
        ))
        // Install global error reporting → broker /log (port of error_reporter.installErrorReporting).
        ErrorReporter.install(broker: services.broker)
    }

    var body: some View {
        Group {
            switch session.phase {
            case .loading:
                ProgressView().controlSize(.large)
            case .signedOut:
                LoginView()
            case .signedIn:
                BiometricGateView {
                    DashboardView(store: DashboardStore(services: services))
                }
            }
        }
        .environment(session)
        .environment(theme)
        .environment(\.appServices, services)
        .preferredColorScheme(theme.mode.colorScheme)
        .task { session.start() }
        .onAppear {
            // Route Perf summaries to the broker /log (pull with tools/render_logs.py --text PERF).
            let broker = services.broker
            Perf.setSink { summary, ctx in broker.logPerf(summary: summary, context: ctx) }
        }
    }
}

extension AppThemeMode {
    /// Map to SwiftUI's optional ColorScheme (nil = follow the system).
    var colorScheme: ColorScheme? {
        switch self {
        case .system: return nil
        case .light: return .light
        case .dark: return .dark
        }
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

// AppServices is injected via @Environment using a classic EnvironmentKey (no macro, iOS-17 safe).
private struct AppServicesKey: EnvironmentKey {
    static let defaultValue: AppServices? = nil
}
extension EnvironmentValues {
    var appServices: AppServices? {
        get { self[AppServicesKey.self] }
        set { self[AppServicesKey.self] = newValue }
    }
}
#endif
