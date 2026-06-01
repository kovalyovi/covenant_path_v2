#if canImport(UIKit)
import SwiftUI

/// What's left to do: a category selector (one milestone at a time, each with its outstanding count),
/// then the *eligible* members still missing that step, with a per-unit summary. Same org filter as
/// Golden Hour, all on by default. Faithful port of `_NeedsView`.
struct NeedsView: View {
    let rows: [Member]

    @State private var selected: Int?       // milestone index; defaults to first non-empty category
    @State private var ascending = true     // baptism-date order: oldest (most overdue) first
    @State private var orgs: Set<OrgBucket> = Set(OrgBucket.allCases)

    private var allOrgs: Bool { orgs.count == OrgBucket.allCases.count }

    /// Baptized members after the org filter (Needs is about converts the org now watches over).
    private var baptized: [Member] {
        let base = rows.filter { !$0.isInvestigator }
        return allOrgs ? base : base.filter { Org.responsible(for: $0).map { orgs.contains($0) } ?? false }
    }

    /// Per-milestone "still need" lists, each sorted by baptism date then unit.
    private var missingByMilestone: [[Member]] {
        Milestones.all.map { ms in
            Milestones.missing(ms, in: baptized).sorted(by: compare)
        }
    }

    private var total: Int { missingByMilestone.reduce(0) { $0 + $1.count } }

    private var selectedIndex: Int {
        if let selected { return selected }
        return missingByMilestone.firstIndex { !$0.isEmpty } ?? 0
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                BigHeader(title: "Needs Action",
                          subtitle: "Eligible members still missing each integration step",
                          accent: DashboardTab.needs.accent)

                OrgFilterBar(selected: $orgs)
                if !allOrgs && orgs.count == 1 {
                    SubtleNote(Org.responsibilityNote(orgs.first!))
                }

                if total == 0 {
                    EmptyHint(allOrgs
                              ? "Nothing outstanding — everyone eligible is on track. 🎉"
                              : "Nothing outstanding for the selected orgs. 🎉")
                } else {
                    categorySelector
                    sortRow
                    categorySection
                }
            }
            .padding(16)
            .frame(maxWidth: 760)
            .frame(maxWidth: .infinity)
        }
    }

    // MARK: - pieces

    private var categorySelector: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                ForEach(Array(Milestones.all.enumerated()), id: \.element.id) { i, ms in
                    CategoryChip(milestone: ms, count: missingByMilestone[i].count,
                                 selected: i == selectedIndex) {
                        selected = i
                    }
                }
            }
        }
    }

    private var sortRow: some View {
        HStack(spacing: 6) {
            Image(systemName: "arrow.up.arrow.down").font(.caption).foregroundStyle(.secondary)
            Text("Baptism date, then unit").font(.caption).foregroundStyle(.secondary)
            Button {
                ascending.toggle()
            } label: {
                Image(systemName: ascending ? "arrow.up" : "arrow.down")
            }
            .font(.caption)
        }
    }

    private var categorySection: some View {
        let ms = Milestones.all[selectedIndex]
        let missing = missingByMilestone[selectedIndex]
        let byUnit = Dictionary(grouping: missing) { $0.unitName ?? "—" }
            .map { (unit: $0.key, count: $0.value.count) }
            .sorted { $0.count > $1.count }
        return SectionCard(title: "Needs \(ms.label)", systemImage: ms.style.symbol,
                           iconColor: Color(hex: ms.style.hex),
                           trailing: AnyView(CountBadge(missing.count))) {
            if missing.isEmpty {
                Text("Everyone eligible has this. 🎉").foregroundStyle(.secondary)
            } else {
                VStack(alignment: .leading, spacing: 0) {
                    FlowLayout(spacing: 6) {
                        ForEach(byUnit, id: \.unit) { e in
                            UnitCountChip(unit: e.unit, count: e.count)
                        }
                    }
                    Divider().padding(.vertical, 8)
                    // Needs rows show the responsible-org chip (showResponsible) and the unit metadata.
                    MemberList(members: missing, showChips: false, showUnit: true, showResponsible: true)
                }
            }
        }
    }

    // MARK: - sorting (baptism date, then unit; honoring asc/desc) — mirrors `_cmp`

    private func compare(_ a: Member, _ b: Member) -> Bool {
        let da = MemberDate.parse(a.baptismDate), db = MemberDate.parse(b.baptismDate)
        var c: Int
        switch (da, db) {
        case (nil, nil): c = 0
        case (nil, _): c = 1
        case (_, nil): c = -1
        case let (x?, y?): c = x < y ? -1 : (x > y ? 1 : 0)
        }
        if c == 0 {
            c = (a.unitName ?? "").compare(b.unitName ?? "").rawValue
        }
        return ascending ? c < 0 : c > 0
    }
}

/// A category selector chip: icon + label + outstanding-count badge; filled when selected; count 0
/// renders muted (that category is done). Mirrors `_CategoryChip`.
struct CategoryChip: View {
    let milestone: Milestone
    let count: Int
    let selected: Bool
    let action: () -> Void

    var body: some View {
        let done = count == 0
        let base = done ? StatusColor.off : Color(hex: milestone.style.hex)
        let fg: Color = selected ? .white : base
        Button(action: action) {
            HStack(spacing: 7) {
                Image(systemName: done ? "checkmark.circle" : milestone.style.symbol)
                    .font(.system(size: 15))
                Text(milestone.label).font(.system(size: 13, weight: .semibold))
                if !done {
                    Text("\(count)").font(.system(size: 12, weight: .bold))
                        .padding(.horizontal, 7).padding(.vertical, 1)
                        .background(selected ? Color.white.opacity(0.25) : base.opacity(0.16), in: Capsule())
                }
            }
            .foregroundStyle(fg)
            .padding(.horizontal, 14).padding(.vertical, 9)
            .background(selected ? base : base.opacity(0.10), in: Capsule())
            .overlay(Capsule().stroke(base.opacity(selected ? 1 : 0.35), lineWidth: 1))
        }
        .buttonStyle(.plain)
    }
}

/// A small colored chip for a unit's outstanding count (each ward a stable color). Mirrors
/// `_UnitCountChip` + `_unitColor`.
struct UnitCountChip: View {
    let unit: String
    let count: Int

    private static let palette: [UInt32] = [
        0x00695C, 0x4527A0, 0xAD1457, 0x283593, 0x558B2F, 0x6D4C41, 0x00838F, 0xC62828
    ]
    private var color: Color {
        Color(hex: Self.palette[abs(unit.hashValue) % Self.palette.count])
    }

    var body: some View {
        Text("\(unit) · \(count)")
            .font(.system(size: 12, weight: .semibold))
            .foregroundStyle(color)
            .padding(.horizontal, 10).padding(.vertical, 4)
            .background(color.opacity(0.10), in: Capsule())
            .overlay(Capsule().stroke(color.opacity(0.35), lineWidth: 1))
    }
}

/// A larger header with an accent bar, title, and subtitle (mirrors `_BigHeader`).
struct BigHeader: View {
    let title: String
    let subtitle: String
    var accent: Color = .accentColor
    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            RoundedRectangle(cornerRadius: 2).fill(accent).frame(width: 4, height: 34)
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(.title3.bold())
                Text(subtitle).font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
        }
    }
}
#endif
