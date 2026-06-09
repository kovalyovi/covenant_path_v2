#if canImport(UIKit)
import SwiftUI

/// The signed-in shell: a 5-tab `TabView` (Baptisms / Golden Hour / Needs / KPIs / Table), each tab
/// its own `NavigationStack`. Adds the full Flutter shell: a stake switcher title, the freshness chip
/// (tap → dialog + Sync now), a Refresh action, the overflow menu (Sync settings / Generate report /
/// Invite a power user / Admin · Ops / Settings), the syncing + stale-credential banners, skeleton
/// loading and the enrollment-aware empty state. Port of `_DashboardPageState`.
struct DashboardView: View {
    @Environment(SessionStore.self) private var session
    @Environment(\.appServices) private var services
    @Environment(ThemeController.self) private var theme
    @State private var store: DashboardStore
    @State private var tab: DashboardTab = .baptisms

    @State private var sheet: ActiveSheet?
    @State private var freshnessShown = false
    @State private var toast: String?

    init(store: DashboardStore) {
        _store = State(initialValue: store)
    }

    enum ActiveSheet: Identifiable {
        case syncSettings, report, invite, admin, settings, reauth
        var id: Int { hashValue }
    }

    var body: some View {
        TabView(selection: $tab) {
            ForEach(DashboardTab.allCases) { t in
                tabContent(t)
                    .tabItem { Label(t.title, systemImage: t.symbol) }
                    .tag(t)
            }
        }
        .tint(tab.accent)
        .task { if store.state == .idle { await store.load() } }
        .task { await maybeSuggestPasskey() }
        .sheet(item: $sheet) { which in
            sheetView(which)
                .environment(\.appServices, services)
                .environment(theme)
        }
        .overlay(alignment: .bottom) { toastView }
    }

    // MARK: - one tab

    @ViewBuilder
    private func tabContent(_ t: DashboardTab) -> some View {
        NavigationStack {
            VStack(spacing: 0) {
                if store.syncing { SyncingBanner(startedAt: store.syncStartedAt) }
                if store.staleCredential {
                    StaleBanner(state: store.enrollStatus?.credential.state ?? "revoked",
                                isProvider: store.enrollStatus?.credential.isProvider == true,
                                lastError: store.enrollStatus?.credential.lastError) {
                        openReauth()
                    }
                }
                pageBody(t)
            }
            .navigationDestination(for: Member.self) { member in
                PersonDetailView(member: member)
            }
            .toolbar { toolbarContent }
            .tint(t.accent)
            .alert("Data freshness", isPresented: $freshnessShown) {
                if store.brokerAvailable && !store.syncing {
                    Button("Sync now") { triggerSyncNow() }
                }
                Button("Close", role: .cancel) {}
            } message: {
                if let iso = store.lastSyncedAt {
                    Text("Last scraped from LCR:\n\n\(Freshness.exact(iso))"
                         + (store.syncing ? "\n\nSync in progress — fresh data in a few minutes." : ""))
                }
            }
        }
    }

    @ViewBuilder
    private func pageBody(_ t: DashboardTab) -> some View {
        switch store.state {
        case .idle, .loading:
            // Per-tab content-shaped skeleton (N8) so Golden Hour / KPIs don't flash member rows.
            switch t {
            case .goldenHour:    GoldenHourSkeleton()
            case .kpis:          KpiSkeleton()
            default:             MemberListSkeleton()
            }
        case .failed(let message):
            ContentUnavailableView {
                Label("Couldn't load data", systemImage: "exclamationmark.triangle")
            } description: {
                Text(message)
            } actions: {
                Button("Retry") { Task { await store.load() } }
            }
        case .loaded:
            if store.members.isEmpty && t != .kpis {
                EmptyStateView(enrollStatus: store.enrollStatus, brokerAvailable: store.brokerAvailable) {
                    openReauth()
                }
            } else {
                loadedPage(t)
                    .refreshable { await store.refresh() }
            }
        }
    }

    @ViewBuilder
    private func loadedPage(_ t: DashboardTab) -> some View {
        switch t {
        case .baptisms:   BaptismsView(rows: store.members, missionariesByUnit: store.missionariesByUnit)
        case .goldenHour: GoldenHourView(rows: store.members)
        case .needs:      NeedsView(rows: store.members)
        case .kpis:       KPIsView(rows: store.members)
        case .table:      TableView(rows: store.members)
        }
    }

    // MARK: - toolbar (stake switcher · freshness · refresh · overflow)

    @ToolbarContentBuilder
    private var toolbarContent: some ToolbarContent {
        ToolbarItem(placement: .topBarLeading) { stakeTitle }
        ToolbarItemGroup(placement: .topBarTrailing) {
            if let iso = store.lastSyncedAt {
                freshnessChip(iso)
            }
            Button {
                Task { await store.refresh() }
            } label: { Image(systemName: "arrow.clockwise") }
            .accessibilityLabel("Refresh")

            overflowMenu
        }
    }

    @ViewBuilder
    private var stakeTitle: some View {
        if store.stakes.count > 1 {
            Menu {
                ForEach(store.stakes) { s in
                    Button {
                        Task { await store.selectStake(s.id) }
                    } label: {
                        if s.id == store.currentStakeID {
                            Label(s.name ?? "—", systemImage: "checkmark")
                        } else {
                            Text(s.name ?? "—")
                        }
                    }
                }
            } label: {
                HStack(spacing: 2) {
                    Text(store.stakeName).font(.headline).lineLimit(1)
                    Image(systemName: "chevron.down").font(.caption2)
                }
            }
        } else {
            Text(store.stakeName).font(.headline).lineLimit(1)
        }
    }

    private func freshnessChip(_ iso: String) -> some View {
        let stale = Freshness.staleness(iso)
        return Button {
            freshnessShown = true
        } label: {
            HStack(spacing: 4) {
                if store.syncing {
                    ProgressView().controlSize(.mini)
                } else {
                    Image(systemName: stale == .fresh ? "clock.arrow.circlepath" : "clock.badge.exclamationmark")
                }
            }
            .foregroundStyle(stale.color ?? .secondary)
        }
        .accessibilityLabel(store.syncing ? "Syncing" : "Updated \(Freshness.ago(iso))")
    }

    private var overflowMenu: some View {
        Menu {
            Button { sheet = .syncSettings } label: { Label("Sync settings", systemImage: "arrow.triangle.2.circlepath") }
            Button { sheet = .report } label: { Label("Generate report", systemImage: "doc.text") }
            Button { sheet = .invite } label: { Label("Invite a power user", systemImage: "person.badge.plus") }
            if store.isAdmin {
                Button { sheet = .admin } label: { Label("Admin · Ops console", systemImage: "gauge") }
            }
            Button { sheet = .settings } label: { Label("Settings", systemImage: "gearshape") }
        } label: {
            Image(systemName: "ellipsis.circle")
        }
    }

    // MARK: - sheets

    @ViewBuilder
    private func sheetView(_ which: ActiveSheet) -> some View {
        switch which {
        case .syncSettings:
            SyncSettingsSheet(store: store, onToast: showToast)
        case .report:
            ReportSheet(onToast: showToast)
        case .invite:
            InviteView()
        case .admin:
            AdminView()
        case .settings:
            SettingsView(onSignOut: { Task { await session.signOut() } },
                         stakeID: store.currentStake?.id, sheetsEnabled: store.currentStake?.sheetsEnabled ?? false)
        case .reauth:
            ReauthSheet(store: store, onToast: showToast)
        }
    }

    // MARK: - actions

    /// In-app re-auth modal (port of web `openReauth`) — never bounce a signed-in user back to the
    /// login screen. Falls back to sign-out only when the broker isn't configured.
    private func openReauth() {
        if store.brokerAvailable {
            sheet = .reauth
        } else {
            Task { await session.signOut() }
        }
    }

    private func triggerSyncNow() {
        Task {
            let res = await store.syncNow()
            showToast(res.message)
        }
    }

    private func maybeSuggestPasskey() async {
        guard session.passkeyAvailable, !AppPrefs.bool(AppPrefs.passkeySuggested) else { return }
        AppPrefs.setBool(AppPrefs.passkeySuggested, true)
        // A gentle, dismiss-on-its-own toast (the snackbar equivalent).
        try? await Task.sleep(nanoseconds: 1_200_000_000)
        showToast("Tip: add a passkey in Settings to sign in without a password next time.")
    }

    private func showToast(_ message: String) {
        toast = message
        Task {
            try? await Task.sleep(nanoseconds: 4_000_000_000)
            if toast == message { toast = nil }
        }
    }

    @ViewBuilder
    private var toastView: some View {
        if let toast {
            Text(toast)
                .font(.callout)
                .padding(.horizontal, 16).padding(.vertical, 12)
                .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 12))
                .overlay(RoundedRectangle(cornerRadius: 12).stroke(Color(.separator)))
                .padding(.horizontal, 24).padding(.bottom, 60)
                .shadow(radius: 8, y: 2)
                .transition(.move(edge: .bottom).combined(with: .opacity))
        }
    }
}

/// Live "syncing your stake" banner with an elapsed-time counter (port of `_SyncingBanner`).
struct SyncingBanner: View {
    let startedAt: Date?
    @State private var now = Date()
    private let timer = Timer.publish(every: 1, on: .main, in: .common).autoconnect()

    private var elapsed: String {
        guard let startedAt else { return "" }
        let d = Int(now.timeIntervalSince(startedAt))
        let m = d / 60, s = d % 60
        return m > 0 ? " · \(m)m \(s)s elapsed" : " · \(s)s elapsed"
    }

    var body: some View {
        HStack(spacing: 12) {
            ProgressView().controlSize(.small)
            Text("Syncing your stake from LCR — fresh data in a few minutes\(elapsed).")
                .font(.callout)
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 16).padding(.vertical, 10)
        .frame(maxWidth: .infinity)
        // N4: frosted-glass banner (system material) tinted blue, instead of a flat fill — it
        // overlays the scrolling member list, so the material actually frosts the content behind it.
        .background(Color(hex: 0x1565C0).opacity(0.12))
        .background(.ultraThinMaterial)
        .onReceive(timer) { now = $0 }
    }
}

/// Revoked/stale-credential banner (port of web `StaleBanner`). Message + action depend on
/// revoked vs stale, and — when stale — whether YOU are the credential's provider.
struct StaleBanner: View {
    var state: String = "revoked"
    var isProvider: Bool = false
    var lastError: String? = nil
    let onReenroll: () -> Void

    private var message: String {
        if state == "revoked" {
            return "Sync paused — credential revoked. Re-enroll to resume daily updates."
        }
        if isProvider {
            return "Sync stopped — your Church session expired, so this stake’s data isn’t updating. Re-authorize to resume."
        }
        return "This stake’s daily sync has failed. The leader who set it up needs to re-authorize — or you can take it over by signing in with your Church account."
    }

    private var actionLabel: String {
        if state == "revoked" { return "Re-enroll" }
        return isProvider ? "Re-authorize" : "Authorize on my account"
    }

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: "arrow.triangle.2.circlepath").foregroundStyle(.orange)
            Text(message)
                .font(.callout)
            Spacer(minLength: 0)
            Button(actionLabel, action: onReenroll).font(.callout)
        }
        .padding(.horizontal, 16).padding(.vertical, 8)
        .frame(maxWidth: .infinity)
        // N4: frosted-glass banner (system material) tinted amber
        .background(Color.orange.opacity(0.12))
        .background(.ultraThinMaterial)
        .accessibilityHint(lastError ?? "")
    }
}

/// Enrollment-aware empty state (port of web `EmptyState`). Every authorize/re-authorize action
/// opens the in-app re-auth modal — never bounces the signed-in user back to the login screen.
struct EmptyStateView: View {
    let enrollStatus: EnrollmentStatus?
    let brokerAvailable: Bool
    let onAuthorize: () -> Void

    var body: some View {
        let copy = resolve()
        return ContentUnavailableView {
            Label(copy.title, systemImage: "person.2.slash")
        } description: {
            Text(copy.body)
        } actions: {
            if copy.showAction {
                Button(copy.actionLabel, action: onAuthorize).buttonStyle(.borderedProminent)
            }
        }
    }

    private func resolve() -> (title: String, body: String, showAction: Bool, actionLabel: String) {
        let cred = enrollStatus?.credential
        let noRole = enrollStatus?.noRole == true
        if enrollStatus == nil {
            return ("No members visible",
                    "Access is scoped to your LCR calling. Sign in with the email your stake has on file.",
                    false, "")
        }
        if noRole && cred?.isNone == true {
            if brokerAvailable {
                return ("Set up stake sync",
                        "Your stake hasn't set up Covenant Path yet. Authorize with your Church account to start daily data updates — it keeps your stake synced automatically.",
                        true, "Authorize stake sync")
            }
            return ("Stake not set up",
                    "Ask your stake leader to enable Covenant Path by signing in with their Church account. Once set up, sign in with your email code for access.",
                    false, "")
        }
        if cred?.isRevoked == true {
            return ("Sync paused",
                    "The daily sync credential for your stake has been revoked. Re-authorize to resume data updates.",
                    brokerAvailable, "Re-authorize")
        }
        if cred?.isStale == true {
            return ("Sync needs re-authorization",
                    "This stake's daily sync stopped — the Church session that keeps it updated expired. Re-authorize with your Church account to resume updates.",
                    brokerAvailable, "Re-authorize")
        }
        if cred?.isActive == true {
            return ("Setting up your stake…",
                    "Your credential is saved and the first sync is running — your stake's data will appear here in a few minutes. Pull down to refresh. (It also refreshes daily.)",
                    false, "")
        }
        return ("No members visible",
                "Access is derived from your LCR calling. Sign in with the email your stake has on file.",
                false, "")
    }
}
#endif
