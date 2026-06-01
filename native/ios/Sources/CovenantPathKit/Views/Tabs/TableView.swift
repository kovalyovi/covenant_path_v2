#if canImport(UIKit)
import SwiftUI

/// Every covenant-path field for baptized members, color-coded Yes(green)/No(red)/N/A(grey). The
/// Flutter app renders a wide horizontal DataTable; on iOS a horizontally-scrolling grid is awkward,
/// so this PoC uses an idiomatic **sortable list** (the spec explicitly allows "a basic sortable
/// list") — one row per member with the status fields as colored cells, plus a sort menu.
struct TableView: View {
    let rows: [Member]

    /// (header, keyPath, kind) — mirrors `_SpreadsheetView._cols`.
    enum Kind { case text, gender, yesno, recommend }
    struct Column: Identifiable {
        let title: String
        let value: (Member) -> String
        let kind: Kind
        var id: String { title }
    }

    @State private var sortColumn: String = "Member"
    @State private var ascending = true

    private let columns: [Column] = [
        Column(title: "Member", value: { $0.name ?? "" }, kind: .text),
        Column(title: "Sex", value: { $0.sex ?? "" }, kind: .gender),
        Column(title: "Unit", value: { $0.unitName ?? "" }, kind: .text),
        Column(title: "Baptism", value: { $0.baptismDate ?? "" }, kind: .text),
        Column(title: "Member for", value: { membershipShort($0) }, kind: .text),
        Column(title: "Friends", value: { $0.friends ?? "" }, kind: .yesno),
        Column(title: "Aaronic", value: { $0.aaronicPriesthood ?? "" }, kind: .yesno),
        Column(title: "Melch.", value: { $0.melchizedekPriesthood ?? "" }, kind: .yesno),
        Column(title: "Calling", value: { $0.calling ?? "" }, kind: .yesno),
        Column(title: "Has min.", value: { $0.ministeringBrothersSisters ?? "" }, kind: .yesno),
        Column(title: "Gives min.", value: { $0.ministeringAssignment ?? "" }, kind: .yesno),
        Column(title: "Recommend", value: { $0.templeRecommend ?? "" }, kind: .recommend),
        Column(title: "Patriarchal", value: { $0.patriarchalBlessing ?? "" }, kind: .yesno),
        Column(title: "Endowed", value: { $0.livingOrdinance ?? "" }, kind: .yesno),
    ]

    private var baptized: [Member] { rows.filter { !$0.isInvestigator } }

    private var sorted: [Member] {
        guard let col = columns.first(where: { $0.id == sortColumn }) else { return baptized }
        return baptized.sorted {
            let c = col.value($0).lowercased().compare(col.value($1).lowercased())
            return ascending ? c == .orderedAscending : c == .orderedDescending
        }
    }

    /// Status columns to show as colored chips in each row (everything except Member/Unit/Baptism/Member-for).
    private var chipColumns: [Column] { columns.filter { $0.kind == .yesno || $0.kind == .recommend || $0.kind == .gender } }

    var body: some View {
        List {
            Section {
                ForEach(sorted) { m in
                    NavigationLink(value: m) { row(m) }
                }
            } header: {
                HStack {
                    Text("\(baptized.count) member\(baptized.count == 1 ? "" : "s")")
                    Spacer()
                    sortMenu
                }
                .textCase(nil)
            }
        }
        .listStyle(.plain)
    }

    private func row(_ m: Member) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 8) {
                Text(m.displayName).fontWeight(.semibold)
                Spacer()
                Text(m.unitName ?? "").font(.caption).foregroundStyle(.secondary)
            }
            if let baptism = m.baptismDate, !baptism.isEmpty, baptism != "needs-profile-api" {
                Text("Baptized \(baptism)").font(.caption).foregroundStyle(.secondary)
            }
            FlowLayout(spacing: 6) {
                ForEach(chipColumns) { col in
                    let v = col.value(m)
                    if !v.isEmpty { cell(title: col.title, value: v, kind: col.kind) }
                }
            }
        }
        .padding(.vertical, 4)
    }

    /// A color-coded cell chip: "<short label> <value>" with the Yes/No/N-A/recommend coloring.
    private func cell(title: String, value: String, kind: Kind) -> some View {
        let bg = cellColor(value, kind)
        return HStack(spacing: 4) {
            Text(title).font(.caption2).foregroundStyle(.secondary)
            Text(value).font(.caption2.weight(.semibold))
        }
        .padding(.horizontal, 7).padding(.vertical, 3)
        .background(bg ?? Color(.tertiarySystemFill), in: RoundedRectangle(cornerRadius: 6))
    }

    private func cellColor(_ v: String, _ kind: Kind) -> Color? {
        switch kind {
        case .gender:
            if v == "M" { return Color(hex: 0xBBDEFB) }   // blue 100
            if v == "F" { return Color(hex: 0xF8BBD0) }   // pink 100
            return nil
        case .yesno:
            if v == "Yes" { return StatusColor.yes }
            if v == "No" { return StatusColor.no }
            if v == "N/A" { return StatusColor.na }
            return nil
        case .recommend:
            if v == "Active" { return StatusColor.yes }
            if v == "Expired" { return StatusColor.expired }
            if v == "No" { return StatusColor.no }
            return nil
        case .text:
            return nil
        }
    }

    private var sortMenu: some View {
        Menu {
            ForEach(columns.filter { $0.kind == .text }) { col in
                Button {
                    if sortColumn == col.id { ascending.toggle() } else { sortColumn = col.id; ascending = true }
                } label: {
                    Label(col.title, systemImage: sortColumn == col.id
                          ? (ascending ? "arrow.up" : "arrow.down") : "")
                }
            }
        } label: {
            Label("Sort: \(sortColumn)", systemImage: "arrow.up.arrow.down")
                .font(.caption)
        }
    }

    /// Strip the redundant "Member for " prefix (header already says it) — mirrors `_display`.
    private static func membershipShort(_ m: Member) -> String {
        let v = m.membershipDuration ?? ""
        return v.replacingOccurrences(of: #"(?i)^Member for\s*"#, with: "", options: .regularExpression)
    }
}
#endif
