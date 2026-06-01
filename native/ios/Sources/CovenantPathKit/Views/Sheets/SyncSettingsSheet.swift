#if canImport(UIKit)
import SwiftUI

/// Sync settings sheet (port of `_SyncSettingsSheet` + `_ScheduleSection` + `_GoogleDriveSection`):
/// stake / last-synced / members / credential status, "Sync my stake now", "Revoke", the daily-sync
/// schedule (ET hour + Pause/Resume), and the Google Drive section (connect/disconnect, sheet link,
/// reconnect state). All provider-gated, loaded on open with a skeleton.
struct SyncSettingsSheet: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(\.appServices) private var services
    let store: DashboardStore
    let onToast: (String) -> Void

    @State private var status: EnrollmentStatus?
    @State private var loaded = false
    @State private var loadFailed = false

    private var broker: BrokerService? { services?.broker }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 4) {
                    if !loaded {
                        SyncSettingsSkeleton()
                    } else if loadFailed || status == nil {
                        Text("Could not load sync settings — close and try again.").foregroundStyle(.secondary)
                    } else {
                        content(status!)
                    }
                }
                .padding(20)
            }
            .navigationTitle("Sync settings")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .topBarTrailing) { Button("Done") { dismiss() } } }
            .task { await load() }
        }
        .presentationDetents([.large])
    }

    @ViewBuilder
    private func content(_ s: EnrollmentStatus) -> some View {
        let cred = s.credential
        let isProvider = cred.isProvider

        InfoRow(label: "Stake", value: s.stakeName ?? "—")
        InfoRow(label: "Last synced", value: s.lastSyncedAt.map(Freshness.exact) ?? "Never")
        InfoRow(label: "Members", value: "\(s.memberCount)")
        Divider().padding(.vertical, 8)

        if cred.isNone {
            Label {
                VStack(alignment: .leading) {
                    Text("No sync credential")
                    Text("Sign in with your Church account to enable daily updates.")
                        .font(.caption).foregroundStyle(.secondary)
                }
            } icon: { Image(systemName: "exclamationmark.triangle").foregroundStyle(.orange) }
        } else {
            InfoRow(label: "Status", value: cred.isRevoked ? "Revoked" : "Active",
                    color: cred.isRevoked ? .orange : StatusColor.done)
            if let p = cred.principalName { InfoRow(label: "Provided by", value: p) }
            if let e = cred.enrolledAt { InfoRow(label: "Enrolled", value: Freshness.exact(e)) }
            InfoRow(label: "Coverage", value: cred.complete ? "Complete" : "Partial")
        }

        Text("Credentials are encrypted and stored server-side. Your password is never stored.")
            .font(.caption).foregroundStyle(.secondary).padding(.top, 8)

        if isProvider {
            Button {
                Task {
                    dismiss()
                    let res = await store.syncNow()
                    onToast(res.message)
                }
            } label: {
                Label("Sync my stake now", systemImage: "arrow.triangle.2.circlepath").frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent).padding(.top, 16)

            Button(role: .destructive) {
                Task { await revoke(stakeID: s.stakeID) }
            } label: {
                Label("Revoke my sync access", systemImage: "link.badge.plus").frame(maxWidth: .infinity)
            }
            .buttonStyle(.bordered).padding(.top, 8)

            ScheduleSection(broker: broker, onToast: onToast)
        }

        GoogleDriveSection(broker: broker, onToast: onToast)
    }

    private func load() async {
        guard let broker, broker.available else { loaded = true; loadFailed = true; return }
        if let cached = store.enrollStatus {
            status = cached; loaded = true; return
        }
        do {
            let s = try await broker.enrollmentStatus()
            status = s
        } catch {
            loadFailed = true
        }
        loaded = true
    }

    private func revoke(stakeID: String?) async {
        guard let broker, let stakeID else { return }
        do {
            try await broker.revoke(stakeID: stakeID)
            dismiss()
            onToast("Sync access revoked. Data will not update until re-enrolled.")
        } catch {
            onToast("Could not revoke: \(error.localizedDescription)")
        }
    }
}

/// A label/value row (port of `_Row`).
struct InfoRow: View {
    let label: String
    let value: String
    var color: Color?
    var body: some View {
        HStack(alignment: .top) {
            Text(label).foregroundStyle(.secondary).frame(width: 110, alignment: .leading)
            Text(value).fontWeight(color != nil ? .medium : .regular)
                .foregroundStyle(color ?? .primary)
            Spacer(minLength: 0)
        }
        .padding(.vertical, 4)
    }
}

/// Daily-sync schedule (port of `_ScheduleSection`): ET hour dropdown + Pause/Resume. Hidden if the
/// broker reports the user isn't eligible.
struct ScheduleSection: View {
    let broker: BrokerService?
    let onToast: (String) -> Void

    @State private var hour = 7
    @State private var paused = false
    @State private var eligible = false
    @State private var loaded = false
    @State private var busy = false

    var body: some View {
        Group {
            if loaded && eligible {
                VStack(alignment: .leading, spacing: 8) {
                    Divider().padding(.vertical, 8)
                    Label("Daily sync time", systemImage: "clock").font(.headline)
                    Text(paused
                         ? "Automatic daily sync is paused. You can still \"Sync my stake now\" anytime."
                         : "Your stake syncs automatically each day at this time.")
                        .font(.caption).foregroundStyle(.secondary)
                    HStack {
                        Picker("Hour", selection: Binding(get: { hour }, set: { save(hour: $0) })) {
                            ForEach(0..<24, id: \.self) { h in Text(label(h)).tag(h) }
                        }
                        .disabled(busy || paused)
                        Spacer()
                        if busy {
                            ProgressView().controlSize(.small)
                        } else {
                            Button {
                                save(paused: !paused)
                            } label: {
                                Label(paused ? "Resume" : "Pause",
                                      systemImage: paused ? "play.fill" : "pause.fill")
                            }
                            .font(.callout)
                        }
                    }
                }
            }
        }
        .task { await load() }
    }

    private func label(_ h: Int) -> String {
        let ampm = h < 12 ? "AM" : "PM"
        let h12 = h % 12 == 0 ? 12 : h % 12
        return "\(h12):00 \(ampm) ET"
    }

    private func load() async {
        guard let broker else { loaded = true; return }
        do {
            let s = try await broker.getSchedule()
            eligible = (s["eligible"] as? Bool) == true
            hour = (s["hour_et"] as? NSNumber)?.intValue ?? 7
            paused = (s["paused"] as? Bool) == true
        } catch { /* leave hidden */ }
        loaded = true
    }

    private func save(hour: Int? = nil, paused: Bool? = nil) {
        guard let broker else { return }
        let h = hour ?? self.hour
        let p = paused ?? self.paused
        busy = true
        Task {
            do {
                _ = try await broker.setSchedule(hourET: h, paused: p)
                self.hour = h; self.paused = p
            } catch {
                onToast("Could not save schedule: \(error.localizedDescription)")
            }
            busy = false
        }
    }
}

/// Google Drive section (port of `_GoogleDriveSection`): self-gating; connect/disconnect, sheet link,
/// last refreshed, "needs reconnect" amber state. Opens the OAuth URL in the browser.
struct GoogleDriveSection: View {
    let broker: BrokerService?
    let onToast: (String) -> Void

    @State private var status: [String: Any]?
    @State private var busy = false
    @Environment(\.openURL) private var openURL

    var body: some View {
        Group {
            if let s = status, (s["eligible"] as? Bool) == true {
                driveBody(for: s)
            }
        }
        .task { await load() }
    }

    @ViewBuilder
    private func driveBody(for s: [String: Any]) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Divider().padding(.vertical, 8)
            Label("Google Drive", systemImage: "externaldrive.badge.plus").font(.headline)

            if (s["configured"] as? Bool) != true {
                Text("Drive integration isn't enabled on the server yet — your stake's sheet is kept on the shared service account for now.")
                    .font(.caption).foregroundStyle(.secondary)
            } else {
                let connected = (s["connected"] as? Bool) == true
                let needsReconnect = (s["needs_reconnect"] as? Bool) == true
                let sheetURL = s["sheet_url"] as? String
                let lastSynced = s["last_synced_at"] as? String

                if needsReconnect {
                    Text("Google Drive needs reconnecting — the saved access expired, so syncs are using the shared sheet for now. Reconnect to resume writing to your own Drive.")
                        .font(.caption).foregroundStyle(.orange)
                } else {
                    Text(connected
                         ? "Connected as \(s["email"] as? String ?? ""). Your stake's spreadsheet lives in your Drive."
                         : "Connect your Google account so your stake gets its own spreadsheet that you own (the app can only touch the file it creates).")
                        .font(.caption).foregroundStyle(.secondary)
                }
                if connected, let sheetURL, let url = URL(string: sheetURL) {
                    Button { openURL(url) } label: {
                        Label("Open your stake spreadsheet", systemImage: "tablecells").font(.caption)
                    }
                }
                if connected, let lastSynced {
                    Text("Sheet last refreshed \(Freshness.exact(lastSynced)).")
                        .font(.caption2).foregroundStyle(.secondary)
                }
                HStack {
                    if connected {
                        Button { Task { await disconnect() } } label: {
                            Label("Disconnect", systemImage: "link.badge.plus").font(.callout)
                        }
                    } else {
                        Button { Task { await connect() } } label: {
                            Label("Connect Google Drive", systemImage: "externaldrive.badge.plus").font(.callout)
                        }
                        .buttonStyle(.borderedProminent)
                    }
                    Button("Refresh") { Task { await load() } }.font(.callout)
                }
                .disabled(busy)
            }
        }
    }

    private func load() async {
        guard let broker else { return }
        status = try? await broker.googleDriveStatus()
    }
    private func connect() async {
        guard let broker else { return }
        busy = true
        do {
            let r = try await broker.googleDriveStart()
            if let url = (r["url"] as? String).flatMap(URL.init(string:)) {
                openURL(url)
                onToast("Finish in the Google window, then tap \"Refresh\".")
            }
        } catch { onToast("Could not start: \(error.localizedDescription)") }
        busy = false
    }
    private func disconnect() async {
        guard let broker else { return }
        busy = true
        do { _ = try await broker.googleDriveDisconnect(); await load() }
        catch { onToast("Could not disconnect: \(error.localizedDescription)") }
        busy = false
    }
}
#endif
