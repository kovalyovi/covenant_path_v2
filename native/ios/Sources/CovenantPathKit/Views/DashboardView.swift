#if canImport(UIKit)
import SwiftUI

/// The signed-in shell: a 5-tab `TabView` (Baptisms / Golden Hour / Needs / KPIs / Table), each tab
/// its own `NavigationStack` so a tapped member pushes a `PersonDetailView`. The dataset is loaded
/// once into `DashboardStore` (single stake, RLS-scoped) and shared with every tab. Mirrors
/// `DashboardPage` (bottom-nav phone layout).
struct DashboardView: View {
    @Environment(SessionStore.self) private var session
    @State private var store: DashboardStore
    @State private var tab: DashboardTab = .baptisms

    init(store: DashboardStore) {
        _store = State(initialValue: store)
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
    }

    /// One tab: a navigation stack hosting the page for `t`, with a shared toolbar (stake switcher +
    /// freshness + sign out) and the member-detail destination.
    @ViewBuilder
    private func tabContent(_ t: DashboardTab) -> some View {
        NavigationStack {
            pageBody(t)
                .navigationTitle(t.title)
                .navigationBarTitleDisplayMode(.inline)
                .navigationDestination(for: Member.self) { member in
                    PersonDetailView(member: member)
                }
                .toolbar { toolbarContent }
                .tint(t.accent)
        }
    }

    @ViewBuilder
    private func pageBody(_ t: DashboardTab) -> some View {
        switch store.state {
        case .idle, .loading:
            MemberListSkeleton()
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
                emptyState
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

    private var emptyState: some View {
        ContentUnavailableView {
            Label("No members visible", systemImage: "person.2.slash")
        } description: {
            Text("Access is scoped to your LCR calling. Sign in with the email your stake has on "
                 + "file, or ask your stake leader to enable sync.")
        }
    }

    // MARK: - toolbar (stake switcher · freshness · sign out)

    @ToolbarContentBuilder
    private var toolbarContent: some ToolbarContent {
        ToolbarItem(placement: .topBarLeading) {
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
        ToolbarItem(placement: .topBarTrailing) {
            Menu {
                if let iso = store.lastSyncedAt {
                    Label("Updated \(FreshnessFormatter.ago(iso))", systemImage: "clock.arrow.circlepath")
                }
                Button("Refresh", systemImage: "arrow.clockwise") { Task { await store.refresh() } }
                Divider()
                Button("Sign out", systemImage: "rectangle.portrait.and.arrow.right", role: .destructive) {
                    Task { await session.signOut() }
                }
            } label: {
                Image(systemName: "ellipsis.circle")
            }
        }
    }
}

/// "Updated 2h ago" style relative freshness (mirrors `_ago`).
enum FreshnessFormatter {
    static func ago(_ iso: String) -> String {
        guard let date = parseTimestamp(iso) else { return iso }
        let secs = Date().timeIntervalSince(date)
        let mins = Int(secs / 60), hours = Int(secs / 3600), days = Int(secs / 86400)
        if mins < 60 { return "\(max(0, mins))m ago" }
        if hours < 24 { return "\(hours)h ago" }
        return "\(days)d ago"
    }

    static func parseTimestamp(_ iso: String) -> Date? {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let d = f.date(from: iso) { return d }
        f.formatOptions = [.withInternetDateTime]
        return f.date(from: iso)
    }
}
#endif
