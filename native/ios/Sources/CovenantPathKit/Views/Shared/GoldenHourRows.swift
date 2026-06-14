#if canImport(UIKit)
import SwiftUI

/// Golden Hour completion — the user-chosen layout: ONE ROW PER ITEM with a status icon.
///   ✓ done (green check)   ○ not done (outline circle)   ⚠ data issue (amber warning)
/// N/A items are OMITTED entirely (not eligible — handled upstream in `Milestones.goldenHourRows`), so
/// this view never renders an "N/A" row. The ⚠ row is visibly distinct from both done and not-done.
///
/// Faithful port of web `apps/web/src/components/GoldenHourRows.tsx`. Used by the person/friend detail
/// view (and the per-person Baptisms card) to show each Golden Hour step's status at a glance.
struct GoldenHourRows: View {
    let member: Member
    /// `list` lets a caller include the longer-horizon covenants (pass `Milestones.needsCategories`);
    /// defaults to the integration milestones.
    var list: [Milestone] = Milestones.all

    private static let green = Color(hex: 0x2E7D32)
    private static let amber = Color(hex: 0xF9A825)

    var body: some View {
        let rows = Milestones.goldenHourRows(member, list: list)
        if rows.isEmpty {
            Text("No Golden Hour steps apply yet.").font(.callout).foregroundStyle(.secondary)
        } else {
            VStack(alignment: .leading, spacing: 8) {
                ForEach(rows) { row in
                    GoldenHourRowView(row: row)
                }
            }
        }
    }
}

private struct GoldenHourRowView: View {
    let row: Milestones.GhRow

    var body: some View {
        let v = visuals(row.status)
        HStack(spacing: 10) {
            Image(systemName: v.icon)
                .font(.system(size: 17))
                .foregroundStyle(v.color)
                .accessibilityLabel(v.accessibility)
            Text(row.milestone.label)
                .font(.callout)
            Spacer(minLength: 8)
            Text(v.label)
                .font(.caption.weight(.medium))
                .foregroundStyle(v.color)
        }
        // The full description from the single milestone definition is the tooltip equivalent.
        .accessibilityHint(row.milestone.label)
    }

    private func visuals(_ status: Milestones.GhRowStatus)
        -> (icon: String, color: Color, label: String, accessibility: String) {
        switch status {
        case .done:
            return ("checkmark.circle.fill", Color(hex: 0x2E7D32), "Done", "Completed")
        case .issue:
            // A DATA ISSUE — the value should be known but isn't (sentinel / missing). Distinct from
            // N/A (omitted) and from an honest not-done.
            return ("exclamationmark.triangle.fill", Color(hex: 0xF9A825), "Needs data",
                    "Data issue — value unavailable")
        case .notDone:
            return ("circle", Color(.systemGray), "Not yet", "Not yet completed")
        }
    }
}
#endif
