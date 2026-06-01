#if canImport(UIKit)
import SwiftUI

/// Two sub-sections via a segmented control: **New Members** (baptized — completion summary + the
/// member list with milestone chips, org filter + recency window) and **Being Taught**
/// (investigators by planned date). Faithful port of `_GoldenHourView`.
struct GoldenHourView: View {
    let rows: [Member]

    enum Section: String, CaseIterable { case newMembers, beingTaught
        var label: String { self == .newMembers ? "New Members" : "Being Taught" }
    }

    @State private var section: Section = .newMembers
    @State private var window: Recency = .all
    @State private var orgs: Set<OrgBucket> = Set(OrgBucket.allCases)
    /// Drill-down sheet for "still need" lists.
    @State private var drill: MilestoneDrill?

    private var newMembers: [Member] { rows.filter { !$0.isInvestigator } }
    private var beingTaught: [Member] { rows.filter { $0.isInvestigator } }

    private var allOrgs: Bool { orgs.count == OrgBucket.allCases.count }

    /// New members after the recency window + org filter (a convert with no baptism date / no org
    /// shows only when no org filter is applied — matches Flutter).
    private var filteredNewMembers: [Member] {
        newMembers.filter { window.contains($0) }
            .filter { allOrgs || (Org.responsible(for: $0).map { orgs.contains($0) } ?? false) }
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                Picker("Section", selection: $section) {
                    Text("New Members (\(newMembers.count))").tag(Section.newMembers)
                    Text("Being Taught (\(beingTaught.count))").tag(Section.beingTaught)
                }
                .pickerStyle(.segmented)

                if section == .beingTaught {
                    beingTaughtSection
                } else {
                    newMembersSection
                }
            }
            .padding(16)
            .frame(maxWidth: 760)
            .frame(maxWidth: .infinity)
        }
        .sheet(item: $drill) { d in
            MilestoneDrillSheet(label: d.label, missing: d.members)
        }
    }

    // MARK: - Being Taught

    private var beingTaughtSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            SectionHeader(title: "Being Taught", count: beingTaught.count, accent: DashboardTab.goldenHour.accent)
            if beingTaught.isEmpty {
                EmptyHint("No one currently being taught.")
            } else {
                // Sort soonest planned date first (Being Taught default ascending).
                let sorted = beingTaught.sorted { sortByDate($0, $1, field: \.baptismGoalDate, ascending: true) }
                SectionCard(title: "By date") {
                    MemberList(members: sorted, showChips: false, showUnit: true, dateField: .goal)
                }
            }
        }
    }

    // MARK: - New Members

    private var newMembersSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            OrgFilterBar(selected: $orgs)
            if !allOrgs && orgs.count == 1 {
                SubtleNote(Org.responsibilityNote(orgs.first!))
            }

            Picker("Window", selection: $window) {
                ForEach(Recency.allCases) { w in Text(w.label).tag(w) }
            }
            .pickerStyle(.segmented)

            if let range = windowRangeLabel {
                RangePill(range).frame(maxWidth: .infinity)
            }

            SectionHeader(title: "Recently Baptized", count: filteredNewMembers.count,
                          accent: DashboardTab.goldenHour.accent)

            CompletionCard(rows: filteredNewMembers) { label, missing in
                drill = MilestoneDrill(label: label, members: missing)
            }

            if filteredNewMembers.isEmpty {
                EmptyHint("No new members in this window.")
            } else {
                // New Members default newest-baptized first.
                let sorted = filteredNewMembers.sorted { sortByDate($0, $1, field: \.baptismDate, ascending: false) }
                SectionCard(title: "By date") {
                    MemberList(members: sorted, showChips: true, showUnit: true, dateField: .baptism)
                }
            }
        }
    }

    /// Human-readable window the data covers (mirrors `_windowRangeLabel`); nil for All.
    private var windowRangeLabel: String? {
        guard let days = window.days else { return nil }
        let from = Calendar.current.date(byAdding: .day, value: -days, to: Date()) ?? Date()
        let f = from.formatted(.dateTime.month(.abbreviated).day())
        let t = Date().formatted(.dateTime.month(.abbreviated).day().year())
        return "Baptized \(f) – \(t)"
    }

    private func sortByDate(_ a: Member, _ b: Member, field: KeyPath<Member, String?>,
                            ascending: Bool) -> Bool {
        let da = MemberDate.parse(a[keyPath: field])
        let db = MemberDate.parse(b[keyPath: field])
        switch (da, db) {
        case (nil, _): return false       // nils sort last (return 1 in Flutter)
        case (_, nil): return true
        case let (x?, y?): return ascending ? x < y : x > y
        }
    }
}

// MARK: - completion summary

/// "Golden Hour completion": per-milestone % (eligible-only), each tappable to a "still need" list.
/// Mirrors `_CompletionCard` + `_PctStat`.
struct CompletionCard: View {
    let rows: [Member]
    let onTapMilestone: (_ label: String, _ missing: [Member]) -> Void

    var body: some View {
        if rows.isEmpty {
            EmptyView()
        } else {
            SectionCard(title: "Golden Hour completion") {
                FlowLayout(spacing: 18, lineSpacing: 12) {
                    ForEach(Milestones.all) { ms in
                        let c = Milestones.completion(ms, in: rows)
                        if c.eligible > 0 {
                            let pct = Double(c.done) / Double(c.eligible)
                            Button {
                                onTapMilestone(ms.label, Milestones.missing(ms, in: rows))
                            } label: {
                                pctStat(label: ms.label, pct: pct, caption: "\(c.done)/\(c.eligible)")
                            }
                            .buttonStyle(.plain)
                        }
                    }
                }
            }
        }
    }

    private func pctStat(label: String, pct: Double, caption: String) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(alignment: .firstTextBaseline, spacing: 4) {
                Text("\(Int((pct * 100).rounded()))%").font(.title3)
                Text(caption).font(.caption).foregroundStyle(.secondary)
            }
            Text(label).font(.caption).foregroundStyle(.secondary).lineLimit(1)
            ProgressView(value: pct).tint(DashboardTab.goldenHour.accent)
        }
        .frame(width: 124, alignment: .leading)
    }
}

/// Identifiable payload for the drill-down sheet.
struct MilestoneDrill: Identifiable {
    let label: String
    let members: [Member]
    var id: String { label }
}

/// The "Still need: X" bottom sheet listing eligible members missing a milestone (mirrors
/// `_showCategory`).
struct MilestoneDrillSheet: View {
    let label: String
    let missing: [Member]

    var body: some View {
        NavigationStack {
            Group {
                if missing.isEmpty {
                    EmptyHint("Everyone eligible has this. 🎉")
                } else {
                    List(missing) { m in
                        NavigationLink(value: m) {
                            HStack(spacing: 10) {
                                PhotoAvatar(name: m.name, photoURL: m.photoURL, size: 36)
                                VStack(alignment: .leading) {
                                    Text(m.displayName)
                                    Text(m.unitName ?? "").font(.caption).foregroundStyle(.secondary)
                                }
                            }
                        }
                    }
                    .navigationDestination(for: Member.self) { PersonDetailView(member: $0) }
                }
            }
            .navigationTitle("Still need: \(label)")
            .navigationBarTitleDisplayMode(.inline)
        }
        .presentationDetents([.medium, .large])
    }
}

/// A small pill showing the date range the current period covers (mirrors `_RangePill`).
struct RangePill: View {
    let text: String
    init(_ text: String) { self.text = text }
    var body: some View {
        HStack(spacing: 6) {
            Image(systemName: "calendar").font(.caption2)
            Text(text).font(.caption).fontWeight(.medium)
        }
        .foregroundStyle(.secondary)
        .padding(.horizontal, 12).padding(.vertical, 5)
        .background(Color(.tertiarySystemFill), in: Capsule())
    }
}

/// A vertical list of `MemberRow`s with dividers, each wrapped in a NavigationLink to detail. The
/// caller supplies the already-sorted members.
struct MemberList: View {
    let members: [Member]
    var showChips = false
    var showUnit = false
    var showResponsible = false
    var dateField: MemberRow.DateField = .baptism

    var body: some View {
        VStack(spacing: 0) {
            ForEach(Array(members.enumerated()), id: \.element.id) { idx, m in
                if idx > 0 { Divider() }
                NavigationLink(value: m) {
                    MemberRow(member: m, showChips: showChips, showUnit: showUnit,
                              showResponsible: showResponsible, dateField: dateField)
                }
                .buttonStyle(.plain)
            }
        }
    }
}
#endif
