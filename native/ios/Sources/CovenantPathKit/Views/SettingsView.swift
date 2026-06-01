#if canImport(UIKit)
import SwiftUI

/// Grouped Settings (port of `settings_page.dart`): Appearance (theme cycle), Security (Add a
/// passkey [Recommended] + App lock toggle), Support (Contact / Feedback), About & privacy, Account
/// (signed in as <email>; Sign out). Presented as a sheet from the dashboard's overflow menu.
struct SettingsView: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(\.appServices) private var services
    @Environment(ThemeController.self) private var theme
    let onSignOut: () -> Void

    @State private var lockAvailable = false
    @State private var lockOn = false
    @State private var aboutShown = false
    @State private var passkeyMessage: String?
    @State private var supportSheet: SupportKind?
    @State private var supportToast: String?

    enum SupportKind: Int, Identifiable { case contact, feedback; var id: Int { rawValue } }

    private var passkeyAvailable: Bool {
        guard let services else { return false }
        return PasskeyService(broker: services.broker, rpID: services.passkeyRPID).available
    }
    @State private var resolvedEmail = "—"

    var body: some View {
        NavigationStack {
            Form {
                Section("Appearance") {
                    Button {
                        theme.cycle()
                    } label: {
                        HStack {
                            Label("Theme", systemImage: "circle.lefthalf.filled")
                            Spacer()
                            Text(theme.mode.label).foregroundStyle(.secondary)
                            Image(systemName: "chevron.right").font(.caption).foregroundStyle(.tertiary)
                        }
                    }
                    .tint(.primary)
                }

                Section("Security") {
                    if passkeyAvailable {
                        Button {
                            Task { await addPasskey() }
                        } label: {
                            VStack(alignment: .leading, spacing: 2) {
                                Label("Add a passkey", systemImage: "key")
                                Text("Recommended — sign in with your face, fingerprint, or PIN instead of a password")
                                    .font(.caption).foregroundStyle(.secondary)
                            }
                        }
                        .tint(.primary)
                    }
                    if lockAvailable {
                        Toggle(isOn: Binding(get: { lockOn }, set: { toggleLock($0) })) {
                            Label {
                                VStack(alignment: .leading) {
                                    Text("App lock")
                                    Text("Require biometrics to open the app")
                                        .font(.caption).foregroundStyle(.secondary)
                                }
                            } icon: { Image(systemName: "faceid") }
                        }
                    }
                    if !passkeyAvailable && !lockAvailable {
                        Label("No extra security options on this device", systemImage: "lock")
                            .foregroundStyle(.secondary)
                    }
                    if let m = passkeyMessage {
                        Text(m).font(.caption).foregroundStyle(.secondary)
                    }
                }

                Section("Support") {
                    Button { supportSheet = .contact } label: {
                        Label("Contact support", systemImage: "bubble.left.and.bubble.right")
                    }.tint(.primary)
                    Button { supportSheet = .feedback } label: {
                        Label("Send feedback", systemImage: "exclamationmark.bubble")
                    }.tint(.primary)
                    if let supportToast { Text(supportToast).font(.caption).foregroundStyle(.secondary) }
                }

                Section("About") {
                    Button { aboutShown = true } label: {
                        Label("About & privacy", systemImage: "info.circle")
                    }.tint(.primary)
                }

                Section("Account") {
                    LabeledContent {
                        Text(resolvedEmail).foregroundStyle(.secondary)
                    } label: {
                        Label("Signed in as", systemImage: "person.crop.circle")
                    }
                    Button(role: .destructive) {
                        dismiss(); onSignOut()
                    } label: {
                        Label("Sign out", systemImage: "rectangle.portrait.and.arrow.right")
                    }
                }
            }
            .navigationTitle("Settings")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .topBarTrailing) { Button("Done") { dismiss() } } }
            .task { await checkLock() }
            .task { resolvedEmail = (await services?.auth.currentEmail) ?? "—" }
            .alert("About & privacy", isPresented: $aboutShown) {
                Button("Close", role: .cancel) {}
            } message: {
                Text(Disclaimer.long + "\n\nPrivacy\n" + Disclaimer.privacy)
            }
            .sheet(item: $supportSheet) { kind in
                Group {
                    switch kind {
                    case .contact: ContactSupportSheet(onToast: { supportToast = $0 })
                    case .feedback: FeedbackSheet(onToast: { supportToast = $0 })
                    }
                }
                .environment(\.appServices, services)
            }
        }
    }

    private func checkLock() async {
        #if canImport(LocalAuthentication)
        lockAvailable = BiometricService.available()
        lockOn = BiometricService.enabled()
        #endif
    }

    private func toggleLock(_ target: Bool) {
        #if canImport(LocalAuthentication)
        _ = BiometricService.setEnabled(target)
        lockOn = target
        #endif
    }

    private func addPasskey() async {
        guard let services, #available(iOS 16.0, *) else {
            passkeyMessage = "Passkeys aren't available on this build."
            return
        }
        let svc = PasskeyService(broker: services.broker, rpID: services.passkeyRPID)
        do {
            try await svc.register()
            passkeyMessage = "Passkey added — next time, sign in with a passkey (no password)."
        } catch {
            passkeyMessage = "Could not add passkey: \(error.localizedDescription)"
        }
    }
}
#endif
