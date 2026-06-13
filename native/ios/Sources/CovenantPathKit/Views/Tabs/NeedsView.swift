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
    @State private var ward: String?        // nil = Stake (all wards)

    private var allOrgs: Bool { orgs.count == OrgBucket.allCases.count }

    /// Distinct wards in view (for the ward picker), sorted.
    private var wards: [String] {
        Array(Set(rows.filter { !$0.isInvestigator }.compactMap { $0.unitName }.filter { !$0.isEmpty })).sorted()
    }

    /// Baptized members after the org filter + ward picker (Needs is about converts the org watches).
    private var baptized: [Member] {
        let base = rows.filter { !$0.isInvestigator }
        let orgScoped = allOrgs ? base : base.filter { Org.responsible(for: $0).map { orgs.contains($0) } ?? false }
        guard let ward else { return orgScoped }
        return orgScoped.filter { ($0.unitName ?? "") == ward }
    }

    var body: some View {
        // Compute the heavy per-category "still need" lists ONCE per render. (Was a computed property
        // re-evaluated for every chip in the selector → O(categories²) sorts over the whole stake on
        // every layout pass, which iOS 26's glass layout passes multiplied into a hard hang.)
        let wards = self.wards
        let baptized = self.baptized
        let missing = Milestones.needsCategories.map { Milestones.missing($0, in: baptized).sorted(by: compare) }
        let total = missing.reduce(0) { $0 + $1.count }
        let selIdx = selected ?? (missing.firstIndex { !$0.isEmpty } ?? 0)
        return ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                BigHeader(title: "Needs Action",
                          subtitle: "Eligible members still missing each integration step",
                          accent: DashboardTab.needs.accent)

                OrgFilterBar(selected: $orgs)
                if !allOrgs && orgs.count == 1 {
                    SubtleNote(Org.responsibilityNote(orgs.first!))
                }
                if wards.count > 1 {
                    WardPicker(wards: wards, selection: $ward)
                }

                if total == 0 {
                    EmptyHint(allOrgs
                              ? "Nothing outstanding — everyone eligible is on track. 🎉"
                              : "Nothing outstanding for the selected orgs. 🎉")
                } else {
                    categorySelector(missing: missing, selectedIndex: selIdx)
                    sortRow
                    categorySection(missing: missing, selectedIndex: selIdx)
                }
            }
            .padding(16)
            .frame(maxWidth: 760)
            .frame(maxWidth: .infinity)
        }
    }

    // MARK: - pieces

    private func categorySelector(missing: [[Member]], selectedIndex: Int) -> some View {
        // Wrap the category pills to the next line (FlowLayout) instead of horizontal scrolling —
        // matches the OrgFilterBar and the web `.wrap` behaviour. Glass container blends the chips on iOS 26.
        CPGlassGroup(spacing: 8) {
            FlowLayout(spacing: 8) {
                ForEach(Array(Milestones.needsCategories.enumerated()), id: \.element.id) { i, ms in
                    CategoryChip(milestone: ms, count: missing[i].count,
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

    private func categorySection(missing: [[Member]], selectedIndex: Int) -> some View {
        let ms = Milestones.needsCategories[selectedIndex]
        let missingMembers = missing[selectedIndex]
        let byUnit = Dictionary(grouping: missingMembers) { $0.unitName ?? "—" }
            .map { (unit: $0.key, count: $0.value.count) }
            .sorted { $0.count > $1.count }
        // ListSection (not a glass card) so the long member list isn't backed by a tall translucent
        // surface — same fix as Golden Hour, and it avoids the glass-card + LazyVStack hang.
        return ListSection(title: "Needs \(ms.label)", symbol: ms.style.symbol,
                           count: missingMembers.count, accent: Color(hex: ms.style.hex)) {
            if missingMembers.isEmpty {
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
                    MemberList(members: missingMembers, showChips: false, showUnit: true, showResponsible: true)
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
        Button(action: action) {
            HStack(spacing: 7) {
                Image(systemName: done ? "checkmark.circle" : milestone.style.symbol)
                    .font(.system(size: 15))
                Text(milestone.label).font(.system(size: 13, weight: selected ? .bold : .semibold))
                if !done {
                    Text("\(count)").font(.system(size: 12, weight: .bold))
                        .padding(.horizontal, 7).padding(.vertical, 1)
                        .background(base.opacity(0.18), in: Capsule())
                }
            }
            .foregroundStyle(selected ? base : base.opacity(0.7))
            .padding(.horizontal, 14).padding(.vertical, 9)
            // Glass chip matching the Golden Hour org filter (selected = tinted glass + bold).
            .cpGlassChip(tint: base, selected: selected)
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
        // Solid tinted capsule (NOT glass): these render inside the glass "Needs <X>" card, so glass
        // here would nest glass-in-glass.
        Text("\(unit) · \(count)")
            .font(.system(size: 12, weight: .semibold))
            .foregroundStyle(color)
            .padding(.horizontal, 10).padding(.vertical, 4)
            .background(color.opacity(0.12), in: Capsule())
            .overlay(Capsule().strokeBorder(color.opacity(0.32), lineWidth: 1))
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

/// Ward picker below the org filters — one ward or the whole stake (default). The caller hides it
/// when there's only one unit in view.
struct WardPicker: View {
    let wards: [String]
    @Binding var selection: String?
    var body: some View {
        Menu {
            Button("Stake — all wards") { selection = nil }
            Divider()
            ForEach(wards, id: \.self) { w in
                Button(w) { selection = w }
            }
        } label: {
            HStack(spacing: 6) {
                Image(systemName: "building.2")
                Text(selection ?? "Stake — all wards").lineLimit(1)
                Spacer(minLength: 0)
                Image(systemName: "chevron.up.chevron.down").font(.caption2)
            }
            .font(.subheadline)
            .padding(.horizontal, 13).padding(.vertical, 10)
            .frame(maxWidth: 360, alignment: .leading)
            .cpGlass(in: RoundedRectangle(cornerRadius: CP.chipRadius, style: .continuous))
        }
        .buttonStyle(.plain)
    }
}
#endif
