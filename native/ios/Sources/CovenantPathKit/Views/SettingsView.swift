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
    var stakeID: String? = nil       // #5b Google Sheets toggle (nil → hide the section)
    var sheetsEnabled: Bool = false

    @State private var lockAvailable = false
    @State private var lockOn = false
    @State private var aboutShown = false
    @State private var rulesShown = false
    @State private var passkeyMessage: String?
    @State private var supportSheet: SupportKind?
    @State private var supportToast: String?

    enum SupportKind: Int, Identifiable { case contact, feedback; var id: Int { rawValue } }

    private var passkeyAvailable: Bool {
        guard let services else { return false }
        return PasskeyService(broker: services.broker, rpID: services.passkeyRPID).available
    }
    @State private var resolvedEmail = "—"
    @State private var sheetsOn = false       // #5b Google Sheets toggle
    @State private var sheetsBusy = false
    @State private var sheetsError: String?

    /// #4 Rules & definitions — plain-language summary (full reference: docs/RULES.md). Mirrors the
    /// Flutter `showRulesDialog` content; kept in sync across surfaces.
    static let rulesSections: [(String, [String])] = [
        ("Who can see the data", [
            "Access is rebuilt from LCR callings every sync — no manual setup.",
            "A calling can see covenant-path data if it has the progress record, member list, or member profiles (stake presidency / clerks / high council always can).",
            "Stake callings see the whole stake; ward/branch callings see their unit only.",
            "Released leaders lose access automatically next sync. Power users get an exact copy of someone's access.",
        ]),
        ("Priesthood & ordinance eligibility", [
            "Calling applies at 12+, giving ministering at 14+.",
            "Aaronic Priesthood: brothers 12+. Melchizedek: brothers 18+ who have been members 1+ year.",
            "Friends and assigned ministers apply to everyone.",
            "People who don't qualify (age / sex / tenure) show N/A, not \"No\", so stats aren't skewed.",
        ]),
        ("Who watches over a convert", [
            "First year after baptism: the full-time missionaries + ward mission leader.",
            "After a year: Elders Quorum (brothers) / Relief Society (sisters).",
        ]),
        ("Who shows where", [
            "People being taught (not yet baptized) appear only in Baptisms and Golden Hour's \"Being Taught\".",
            "Baptised & confirmed counts use the convert's baptism month.",
        ]),
    ]

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

                if let stakeID {
                    Section("Google Sheets") {
                        Toggle(isOn: Binding(get: { sheetsOn }, set: { newVal in
                            sheetsOn = newVal
                            sheetsBusy = true
                            sheetsError = nil
                            Task {
                                do {
                                    try await services?.gateway.setStakeSheetsEnabled(stakeID: stakeID, enabled: newVal)
                                } catch {
                                    sheetsOn = !newVal
                                    sheetsError = "Only a stake leader can change this."
                                }
                                sheetsBusy = false
                            }
                        })) {
                            VStack(alignment: .leading, spacing: 2) {
                                Text("Generate Google Sheets for this stake")
                                Text("Creates a stake master sheet + a sheet per ward in the authorized leader's Drive, shared read-only with the relevant leaders & missionaries and refreshed each sync. Off by default — the same data is always in this app.")
                                    .font(.caption).foregroundStyle(.secondary)
                            }
                        }
                        .disabled(sheetsBusy)
                        if let sheetsError { Text(sheetsError).font(.caption).foregroundStyle(.red) }
                    }
                }

                Section("About") {
                    Button { aboutShown = true } label: {
                        Label("About & privacy", systemImage: "info.circle")
                    }.tint(.primary)
                    Button { rulesShown = true } label: {
                        Label("Rules & definitions", systemImage: "list.bullet.rectangle")
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
            .onAppear { sheetsOn = sheetsEnabled }
            .task { await checkLock() }
            .task { resolvedEmail = (await services?.auth.currentEmail) ?? "—" }
            .alert("About & privacy", isPresented: $aboutShown) {
                Button("Close", role: .cancel) {}
            } message: {
                Text(Disclaimer.long + "\n\nPrivacy\n" + Disclaimer.privacy)
            }
            .sheet(isPresented: $rulesShown) {
                NavigationStack {
                    ScrollView {
                        VStack(alignment: .leading, spacing: 16) {
                            ForEach(Self.rulesSections, id: \.0) { section in
                                VStack(alignment: .leading, spacing: 4) {
                                    Text(section.0).font(.headline)
                                    ForEach(section.1, id: \.self) { p in
                                        HStack(alignment: .top, spacing: 6) {
                                            Text("•").foregroundStyle(.secondary)
                                            Text(p).font(.callout)
                                        }
                                    }
                                }
                            }
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding()
                    }
                    .navigationTitle("Rules & definitions")
                    .navigationBarTitleDisplayMode(.inline)
                    .toolbar { ToolbarItem(placement: .topBarTrailing) { Button("Done") { rulesShown = false } } }
                }
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
