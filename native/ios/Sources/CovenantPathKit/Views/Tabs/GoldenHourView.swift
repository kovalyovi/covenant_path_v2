#if canImport(UIKit)
import SwiftUI

/// Two sub-sections via a segmented control: **New Members** (baptized — completion summary + the
/// member list with milestone chips, org filter + recency window) and **Being Taught**
/// (investigators by planned date).
///
/// Performance + clarity pass (2026-06-13): member rows render in a **`LazyVStack`** so only the
/// on-screen rows are built (was a non-lazy `VStack` of the whole stake — the source of the scroll
/// jank); filtered/sorted arrays are computed **once** per render instead of on every property read;
/// the completion summary is a horizontal strip of compact tiles instead of a tall wrapping flow; and
/// the stacked control/header pile is folded into fewer, glass surfaces.
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
    /// shows only when no org filter is applied — matches the web client).
    private var filteredNewMembers: [Member] {
        newMembers.filter { window.contains($0) }
            .filter { allOrgs || (Org.responsible(for: $0).map { orgs.contains($0) } ?? false) }
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
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
        // Sort soonest planned date first (Being Taught default ascending) — computed once.
        let sorted = beingTaught.sorted { sortByDate($0, $1, field: \.baptismGoalDate, ascending: true) }
        return VStack(alignment: .leading, spacing: 14) {
            if sorted.isEmpty {
                EmptyHint("No one currently being taught.")
            } else {
                // The long list renders directly (not inside a glass card) so a tall translucent
                // surface isn't composited behind hundreds of rows — cleaner and lighter.
                ListSection(title: "Being taught", symbol: "book.fill", count: sorted.count) {
                    MemberList(members: sorted, showChips: false, showUnit: true, dateField: .goal)
                }
            }
        }
    }

    // MARK: - New Members

    private var newMembersSection: some View {
        // Compute the filtered + sorted list ONCE (was re-derived on every property access).
        let shown = filteredNewMembers
        let sorted = shown.sorted { sortByDate($0, $1, field: \.baptismDate, ascending: false) }
        return VStack(alignment: .leading, spacing: 14) {
            OrgFilterBar(selected: $orgs)
            if !allOrgs && orgs.count == 1 {
                SubtleNote(Org.responsibilityNote(orgs.first!))
            }

            Picker("Window", selection: $window) {
                ForEach(Recency.allCases) { w in Text(w.label).tag(w) }
            }
            .pickerStyle(.segmented)

            CompletionCard(rows: shown) { label, missing in
                drill = MilestoneDrill(label: label, members: missing)
            }

            if shown.isEmpty {
                EmptyHint("No new members in this window.")
            } else {
                ListSection(title: "Recently baptized", symbol: "drop.fill", count: shown.count,
                            caption: windowRangeLabel.map { "\($0) · newest first" }) {
                    MemberList(members: sorted, showChips: true, showUnit: true, dateField: .baptism)
                }
            }
        }
    }

    /// Human-readable window the data covers; nil for All.
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
        case (nil, _): return false       // nils sort last
        case (_, nil): return true
        case let (x?, y?): return ascending ? x < y : x > y
        }
    }
}

// MARK: - completion summary

/// "Golden Hour completion": per-milestone % (eligible-only), each tappable to a "still need" list.
/// Rendered as a horizontal strip of compact tiles so it stays one band tall regardless of how many
/// milestones apply (the old wrapping flow grew very tall and cluttered).
struct CompletionCard: View {
    let rows: [Member]
    let onTapMilestone: (_ label: String, _ missing: [Member]) -> Void

    /// Eligible-only completion per milestone — computed once and reused by the body.
    private var stats: [Stat] {
        Milestones.all.compactMap { ms in
            let c = Milestones.completion(ms, in: rows)
            return c.eligible > 0 ? Stat(ms: ms, done: c.done, eligible: c.eligible) : nil
        }
    }

    private struct Stat: Identifiable {
        let ms: Milestone; let done: Int; let eligible: Int
        var id: String { ms.id }
        var pct: Double { Double(done) / Double(eligible) }
    }

    var body: some View {
        let s = stats
        if rows.isEmpty || s.isEmpty {
            EmptyView()
        } else {
            SectionCard(title: "Golden Hour completion") {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 10) {
                        ForEach(s) { stat in
                            Button {
                                onTapMilestone(stat.ms.label, Milestones.missing(stat.ms, in: rows))
                            } label: {
                                tile(stat)
                            }
                            .buttonStyle(.plain)
                        }
                    }
                    .padding(.vertical, 2)
                }
            }
        }
    }

    private func tile(_ stat: Stat) -> some View {
        let accent = DashboardTab.goldenHour.accent
        return VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .firstTextBaseline, spacing: 4) {
                Text("\(Int((stat.pct * 100).rounded()))%")
                    .font(.title3.weight(.semibold)).monospacedDigit()
                Text("\(stat.done)/\(stat.eligible)")
                    .font(.caption2).foregroundStyle(.secondary)
            }
            Text(stat.ms.label).font(.caption2.weight(.medium)).foregroundStyle(.secondary).lineLimit(1)
            ProgressView(value: stat.pct).tint(accent)
        }
        .frame(minWidth: 120, alignment: .leading)   // grows (not clips) at large Dynamic Type
        .padding(12)
        // A subtle tinted fill — NOT glass — so we don't nest glass inside the glass card.
        .background(accent.opacity(0.10), in: RoundedRectangle(cornerRadius: 14, style: .continuous))
    }
}

/// Identifiable payload for the drill-down sheet.
struct MilestoneDrill: Identifiable {
    let label: String
    let members: [Member]
    var id: String { label }
}

/// The "Still need: X" bottom sheet listing eligible members missing a milestone.
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

/// A small pill showing the date range the current period covers.
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
        .cpGlass(in: Capsule())
    }
}

/// A lightweight list-section header (accent glyph + title + count + optional caption) followed by its
/// rows rendered DIRECTLY on the screen background — **no enclosing card**, so a long `LazyVStack` isn't
/// backed by a tall translucent surface (that backing layer + its growth was the remaining cost after
/// the rows themselves went lazy). Used for the Golden Hour member lists.
struct ListSection<Content: View>: View {
    let title: String
    let symbol: String
    let count: Int
    var caption: String?
    let accent: Color
    let content: () -> Content

    init(title: String, symbol: String, count: Int, caption: String? = nil,
         accent: Color = DashboardTab.goldenHour.accent,
         @ViewBuilder content: @escaping () -> Content) {
        self.title = title; self.symbol = symbol; self.count = count
        self.caption = caption; self.accent = accent; self.content = content
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                Label(title, systemImage: symbol).font(.headline).foregroundStyle(accent)
                CountBadge(count)
                Spacer(minLength: 0)
            }
            if let caption {
                Text(caption).font(.caption).foregroundStyle(.secondary)
            }
            content()
        }
    }
}

/// A **lazy** vertical list of `MemberRow`s with dividers, each wrapped in a NavigationLink to detail.
/// `LazyVStack` is the key scroll-performance fix: rows are built only as they scroll into view (and
/// torn down as they leave), so a stake with hundreds of converts no longer materializes every avatar
/// + chip row up front. Shared by Golden Hour and Needs; the caller supplies the already-sorted members.
struct MemberList: View {
    let members: [Member]
    var showChips = false
    var showUnit = false
    var showResponsible = false
    var dateField: MemberRow.DateField = .baptism

    var body: some View {
        LazyVStack(spacing: 0) {
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
