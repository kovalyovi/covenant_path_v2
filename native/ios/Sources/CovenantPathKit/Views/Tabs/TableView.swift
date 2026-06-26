#if canImport(UIKit)
import SwiftUI

/// Every covenant-path field for baptized members in a sortable, per-column-value-filterable grid,
/// color-coded Yes(green)/No(red)/N-A(grey)/recommend. Faithful port of `_SpreadsheetView`: a
/// horizontally-scrolling table (the spec's iOS pattern), 3-state sort on text columns, a value-picker
/// filter dialog per column, "N members (filtered)" + clear-filters, and row → detail.
struct TableView: View {
    @Environment(DashboardStore.self) private var store: DashboardStore?
    let rows: [Member]

    enum Kind { case text, gender, yesno, recommend, friends }
    struct Column: Identifiable {
        let title: String
        let value: (Member) -> String
        let kind: Kind
        var id: String { title }
        var sortable: Bool { kind == .text }
    }

    @State private var sortColumn: String?      // nil = no sort (3-state: asc → desc → none)
    @State private var ascending = true
    /// Per-column EXCLUDED values (the unchecked ones). A row passes if none of its values excluded.
    @State private var excluded: [String: Set<String>] = [:]
    @State private var filterColumn: Column?
    /// Horizontal scroll offset of the data region, mirrored onto the frozen header so its column
    /// labels track the columns beneath them (the frozen first row + first column pattern).
    @State private var dataOffsetX: CGFloat = 0

    private let columns: [Column] = [
        Column(title: "Member", value: { $0.name ?? "" }, kind: .text),
        Column(title: "Sex", value: { $0.sex ?? "" }, kind: .gender),
        Column(title: "Age", value: { Milestones.ageNow($0).map(String.init) ?? "" }, kind: .text),
        Column(title: "Unit", value: { $0.unitName ?? "" }, kind: .text),
        Column(title: "Baptism", value: { $0.baptismDate ?? "" }, kind: .text),
        Column(title: "Member for", value: { membershipShort($0) }, kind: .text),
        Column(title: "Friends", value: { $0.friendsCount.map(String.init) ?? ($0.friends ?? "") }, kind: .friends),
        Column(title: "Aaronic", value: { $0.aaronicPriesthood ?? "" }, kind: .yesno),
        Column(title: "Melch.", value: { $0.melchizedekPriesthood ?? "" }, kind: .yesno),
        Column(title: "Calling", value: { $0.calling ?? "" }, kind: .yesno),
        Column(title: "Has min.", value: { $0.ministeringBrothersSisters ?? "" }, kind: .yesno),
        Column(title: "Gives min.", value: { $0.ministeringAssignment ?? "" }, kind: .yesno),
        Column(title: "Recommend", value: { $0.templeRecommend ?? "" }, kind: .recommend),
        Column(title: "Patriarchal", value: { $0.patriarchalBlessing ?? "" }, kind: .yesno),
        Column(title: "Endowed", value: { $0.livingOrdinance ?? "" }, kind: .yesno),
        Column(title: "1st temple visit", value: { Milestones.firstTempleVisitDisplay($0) }, kind: .yesno),
        Column(title: "Family name", value: { Milestones.familyNameDisplay($0) }, kind: .yesno),
    ]

    private var baptized: [Member] { rows.filter { !$0.isInvestigator } }

    private func passes(_ m: Member) -> Bool {
        for (key, set) in excluded {
            if let col = columns.first(where: { $0.id == key }), set.contains(col.value(m)) { return false }
        }
        return true
    }

    private var filtered: [Member] {
        var r = baptized.filter(passes)
        if let sortColumn, let col = columns.first(where: { $0.id == sortColumn }) {
            r.sort {
                if col.title == "Age" {   // age sorts numerically, not as a string
                    let a = Milestones.ageNow($0) ?? -1, b = Milestones.ageNow($1) ?? -1
                    return ascending ? a < b : a > b
                }
                let c = col.value($0).lowercased().compare(col.value($1).lowercased())
                return ascending ? c == .orderedAscending : c == .orderedDescending
            }
        }
        return r
    }

    private var activeFilters: Int { excluded.values.filter { !$0.isEmpty }.count }

    // Column widths so the header + cells line up in the horizontal scroll.
    private func width(_ col: Column) -> CGFloat {
        switch col.title {
        case "Member": return 150
        case "Unit": return 130
        case "Baptism": return 110
        case "Member for": return 110
        case "Sex", "Age": return 56
        default: return 92
        }
    }
    private let rowNumWidth: CGFloat = 40
    // Fixed row/header heights so the frozen first column and the scrolling data column stay aligned.
    private let rowH: CGFloat = 44
    private let hdrH: CGFloat = 44

    var body: some View {
        let rowsF = Perf.measure("compute.table") { filtered }   // filter + sort once (instrumented)
        let memberCol = columns[0]                // "Member" — the frozen first column
        let dataCols = Array(columns.dropFirst())
        let frozenW = rowNumWidth + width(memberCol)
        return VStack(spacing: 0) {
            HStack {
                Text("\(rowsF.count) member\(rowsF.count == 1 ? "" : "s")"
                     + (activeFilters > 0 ? " (filtered)" : ""))
                    .font(.footnote).foregroundStyle(.secondary)
                Spacer()
                if activeFilters > 0 {
                    Button {
                        excluded.removeAll()
                    } label: {
                        Label("Clear \(activeFilters) filter\(activeFilters == 1 ? "" : "s")",
                              systemImage: "line.3.horizontal.decrease.circle").font(.caption)
                    }
                }
            }
            .padding(.horizontal, 12).padding(.vertical, 8)

            // FROZEN header row (row 1): the corner (# + Member) stays put; the data headers mirror the
            // body's horizontal scroll so each label sits above its column.
            HStack(alignment: .center, spacing: 0) {
                cornerHeader(memberCol: memberCol).frame(width: frozenW)
                dataHeaderRow(cols: dataCols)
                    .offset(x: dataOffsetX)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .clipped()
            }
            .frame(height: hdrH)
            .cpGlass(in: Rectangle())
            .overlay(alignment: .bottom) { Divider() }
            .zIndex(1)

            // BODY: a frozen first column beside the horizontally-scrolling data, sharing ONE vertical
            // scroll so they move together. (Frozen columns have no native SwiftUI support — this is the
            // standard split + offset-mirror pattern.)
            ScrollView(.vertical, showsIndicators: true) {
                // LazyVStack (was VStack): virtualize rows so switching to Table builds ~a screenful
                // instead of the whole stake × 17 columns. The frozen row/column come from the pinned
                // header + offset-mirror, NOT from non-laziness, so this is preserved. Fixed rowH keeps
                // the two lazy columns aligned.
                HStack(alignment: .top, spacing: 0) {
                    LazyVStack(spacing: 0) {
                        ForEach(Array(rowsF.enumerated()), id: \.element.id) { idx, m in
                            NavigationLink(value: m) { frozenRowCell(idx: idx, m: m, memberCol: memberCol) }
                                .buttonStyle(.plain)
                            Divider()
                        }
                    }
                    .frame(width: frozenW)
                    .overlay(alignment: .trailing) { Divider() }
                    .zIndex(1)

                    ScrollView(.horizontal, showsIndicators: true) {
                        LazyVStack(spacing: 0) {
                            ForEach(Array(rowsF.enumerated()), id: \.element.id) { _, m in
                                NavigationLink(value: m) { dataRowCells(m: m, cols: dataCols) }
                                    .buttonStyle(.plain)
                                Divider()
                            }
                        }
                        .background(GeometryReader { g in
                            Color.clear.preference(key: HOffsetKey.self,
                                                   value: g.frame(in: .named("tableH")).minX)
                        })
                    }
                    .coordinateSpace(name: "tableH")
                }
            }
        }
        .onPreferenceChange(HOffsetKey.self) { dataOffsetX = $0 }
        .sheet(item: $filterColumn) { col in
            ColumnFilterSheet(
                title: col.title,
                values: distinctValues(col),
                // Covenant-path columns route their value labels through the display contract so the
                // filter list never shows the raw "needs-profile-api"/"blocked:…" sentinel either.
                isCovenant: col.kind == .yesno || col.kind == .recommend || col.kind == .friends,
                isAdmin: isAdmin,
                excluded: excluded[col.id] ?? [],
                onApply: { newExcluded in
                    if newExcluded.isEmpty { excluded.removeValue(forKey: col.id) }
                    else { excluded[col.id] = newExcluded }
                })
        }
    }

    /// Frozen top-left corner: the "#" + the Member column header (sort/filter intact).
    private func cornerHeader(memberCol: Column) -> some View {
        HStack(spacing: 0) {
            Text("#").font(.caption.bold()).foregroundStyle(.secondary)
                .frame(width: rowNumWidth, alignment: .leading).padding(.horizontal, 6)
            headerCell(memberCol).frame(width: width(memberCol), alignment: .leading).padding(.horizontal, 6)
        }
    }

    /// The non-frozen column headers (everything after Member), at intrinsic full width.
    private func dataHeaderRow(cols: [Column]) -> some View {
        HStack(spacing: 0) {
            ForEach(cols) { col in
                headerCell(col).frame(width: width(col), alignment: .leading).padding(.horizontal, 6)
            }
        }
    }

    private func headerCell(_ col: Column) -> some View {
        HStack(spacing: 3) {
            Text(col.title).font(.caption.bold()).foregroundStyle(.primary).lineLimit(1)
            if col.sortable {
                Button { toggleSort(col) } label: {
                    Image(systemName: sortColumn == col.id
                          ? (ascending ? "arrow.up" : "arrow.down") : "arrow.up.arrow.down")
                        .font(.caption2)
                        .foregroundStyle(sortColumn == col.id ? Color.accentColor : Color.secondary)
                }
            }
            Button { filterColumn = col } label: {
                Image(systemName: (excluded[col.id]?.isEmpty == false) ? "line.3.horizontal.decrease.circle.fill" : "line.3.horizontal.decrease.circle")
                    .font(.caption2)
                    .foregroundStyle((excluded[col.id]?.isEmpty == false) ? Color.accentColor : Color.secondary)
            }
        }
    }

    /// Frozen first column for a row: the row number + the Member name (with a note marker).
    private func frozenRowCell(idx: Int, m: Member, memberCol: Column) -> some View {
        HStack(spacing: 0) {
            Text("\(idx + 1)").font(.caption).foregroundStyle(.secondary)
                .frame(width: rowNumWidth, alignment: .leading).padding(.horizontal, 6)
            HStack(spacing: 4) {
                cell(tableShortName(memberCol.value(m)), memberCol.kind)
                if let uuid = m.personUUID, store?.notes[uuid] != nil {
                    Image(systemName: "note.text").font(.caption2).foregroundStyle(Color.accentColor)
                }
            }
            .frame(width: width(memberCol), alignment: .leading).padding(.horizontal, 6)
        }
        .frame(height: rowH)
        .contentShape(Rectangle())
    }

    /// The non-frozen cells for a row (everything after Member).
    private func dataRowCells(m: Member, cols: [Column]) -> some View {
        HStack(spacing: 0) {
            ForEach(cols) { col in
                cell(col.value(m), col.kind)
                    .frame(width: width(col), alignment: .leading).padding(.horizontal, 6)
            }
        }
        .frame(height: rowH)
        .contentShape(Rectangle())
    }

    /// Table-only short name: "First L" — first name + last initial, dropping any middle name
    /// ("Kovaliov, Ilya James" → "Ilya K"). Names arrive "Last, First [Middle…]". Only the rendered
    /// cell text is shortened — sort/filter still use the full value (mirrors web abbreviateName).
    private func tableShortName(_ n: String) -> String {
        guard let comma = n.firstIndex(of: ",") else { return n }
        let last = n[..<comma].trimmingCharacters(in: .whitespaces)
        let rest = n[n.index(after: comma)...].trimmingCharacters(in: .whitespaces)
        guard let first = rest.split(separator: " ").first.map(String.init),
              let initial = last.first else { return n }
        return "\(first) \(initial)"
    }

    /// Whether the signed-in user is an admin — an admin may see the raw sentinel string in a
    /// data-issue cell (to diagnose); a regular leader sees only the ⚠.
    private var isAdmin: Bool { store?.isAdmin == true }

    @ViewBuilder
    private func cell(_ value: String, _ kind: Kind) -> some View {
        // Covenant-path value columns flow through the display contract so the raw "needs-profile-api"
        // / "blocked: …" sentinel (or an empty value) NEVER leaks into a leader's cell — it shows a ⚠
        // data-issue marker instead (mirrors web fieldDisplay; the sheet maps the same sentinel to
        // empty). Non-covenant columns (Member name, Unit, Sex, Age, …) render verbatim.
        if kind == .yesno || kind == .recommend || kind == .friends {
            covenantCell(value, kind)
        } else if let bg = cellColor(value, kind) {
            Text(value).font(.caption.weight(.medium))
                .padding(.horizontal, 7).padding(.vertical, 3)
                .background(bg, in: RoundedRectangle(cornerRadius: 6))
                .foregroundStyle(.black)
        } else {
            Text(value).font(.caption).lineLimit(1)
        }
    }

    /// A covenant-path field cell that honors the display contract:
    ///   • a real value (Yes/No/Active/Expired/a count) → its color-coded chip;
    ///   • "N/A" → a quiet grey chip, never a warning;
    ///   • the sentinel OR empty → a ⚠ data-issue marker (admins additionally see the raw string).
    @ViewBuilder
    private func covenantCell(_ value: String, _ kind: Kind) -> some View {
        let d = FieldDisplayLogic.classify(value, isAdmin: isAdmin)
        switch d.status {
        case .issue:
            HStack(spacing: 3) {
                Image(systemName: "exclamationmark.triangle.fill")
                    .font(.caption2).foregroundStyle(Color(hex: 0xF9A825))
                if !d.text.isEmpty {   // admins see the raw sentinel for diagnosis
                    Text(d.text).font(.caption2).foregroundStyle(.secondary).lineLimit(1)
                }
            }
            .accessibilityLabel("Data issue — value unavailable")
        case .na:
            Text("N/A").font(.caption.weight(.medium))
                .padding(.horizontal, 7).padding(.vertical, 3)
                .background(StatusColor.na, in: RoundedRectangle(cornerRadius: 6))
                .foregroundStyle(.black)
        case .value:
            if let bg = cellColor(d.text, kind) {
                Text(d.text).font(.caption.weight(.medium))
                    .padding(.horizontal, 7).padding(.vertical, 3)
                    .background(bg, in: RoundedRectangle(cornerRadius: 6))
                    .foregroundStyle(.black)
            } else {
                Text(d.text).font(.caption).lineLimit(1)
            }
        }
    }

    private func cellColor(_ v: String, _ kind: Kind) -> Color? {
        switch kind {
        case .gender:
            if v == "M" { return Color(hex: 0xBBDEFB) }
            if v == "F" { return Color(hex: 0xF8BBD0) }
            return nil
        case .yesno:
            if v == "Yes" { return StatusColor.yes }
            if v == "No" { return StatusColor.no }
            if v == "N/A" { return StatusColor.na }
            return nil
        case .friends:
            if let n = Int(v) { return n > 0 ? StatusColor.yes : StatusColor.no }
            if v == "Yes" { return StatusColor.yes }
            if v == "No" { return StatusColor.no }
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

    private func toggleSort(_ col: Column) {
        if sortColumn == col.id {
            if ascending { ascending = false } else { sortColumn = nil }  // asc → desc → none
        } else {
            sortColumn = col.id; ascending = true
        }
    }

    /// Distinct values for a column, with counts, for the filter dialog.
    private func distinctValues(_ col: Column) -> [(value: String, count: Int)] {
        var counts: [String: Int] = [:]
        for m in baptized { counts[col.value(m), default: 0] += 1 }
        return counts.map { (value: $0.key, count: $0.value) }.sorted { $0.value < $1.value }
    }

    /// Strip the redundant "Member for " prefix (header already says it) — mirrors `_display`.
    private static func membershipShort(_ m: Member) -> String {
        let v = m.membershipDuration ?? ""
        return v.replacingOccurrences(of: #"(?i)^Member for\s*"#, with: "", options: .regularExpression)
    }
}

/// Carries the data region's horizontal scroll offset up to the frozen header (so its labels track
/// the columns beneath them). One-directional (body → header); no scroll feedback loop.
private struct HOffsetKey: PreferenceKey {
    static var defaultValue: CGFloat = 0
    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) { value = nextValue() }
}

/// Google-Sheets-style value picker (port of `_openFilter`): each distinct value with a checkbox;
/// unchecking hides rows with that value. Select all / Clear all + Apply.
struct ColumnFilterSheet: View {
    @Environment(\.dismiss) private var dismiss
    let title: String
    let values: [(value: String, count: Int)]
    var isCovenant = false
    var isAdmin = false
    let onApply: (Set<String>) -> Void

    @State private var excluded: Set<String>

    init(title: String, values: [(value: String, count: Int)],
         isCovenant: Bool = false, isAdmin: Bool = false, excluded: Set<String>,
         onApply: @escaping (Set<String>) -> Void) {
        self.title = title; self.values = values
        self.isCovenant = isCovenant; self.isAdmin = isAdmin; self.onApply = onApply
        _excluded = State(initialValue: excluded)
    }

    /// The human-facing label for a filter value: covenant columns never show the raw sentinel to a
    /// leader (it becomes "Data issue"); an empty value reads "(blank)". Mirrors the cell contract.
    private func display(_ value: String) -> String {
        if isCovenant {
            let d = FieldDisplayLogic.classify(value, isAdmin: isAdmin)
            if d.status == .issue {
                return d.text.isEmpty ? "Data issue" : "Data issue (\(d.text))"
            }
        }
        return value.isEmpty ? "(blank)" : value
    }

    var body: some View {
        NavigationStack {
            List {
                Section {
                    HStack {
                        Button("Select all") { excluded.removeAll() }
                        Spacer()
                        Button("Clear all") { excluded = Set(values.map { $0.value }) }
                    }
                    .font(.callout)
                }
                ForEach(values, id: \.value) { v in
                    Button {
                        if excluded.contains(v.value) { excluded.remove(v.value) } else { excluded.insert(v.value) }
                    } label: {
                        HStack {
                            Image(systemName: excluded.contains(v.value) ? "square" : "checkmark.square.fill")
                                .foregroundStyle(excluded.contains(v.value) ? .secondary : Color.accentColor)
                            Text(display(v.value)).foregroundStyle(.primary)
                            Spacer()
                            Text("\(v.count)").font(.caption).foregroundStyle(.secondary)
                        }
                    }
                }
            }
            .navigationTitle("Filter · \(title)")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Apply") { onApply(excluded); dismiss() }
                }
            }
        }
        .presentationDetents([.medium, .large])
    }
}
#endif
