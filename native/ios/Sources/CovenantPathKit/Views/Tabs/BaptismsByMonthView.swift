#if canImport(UIKit)
import SwiftUI

/// Dedicated "By Month" tab (the last tab): baptized-convert counts by baptism month, with its own
/// window filter that defaults to year-to-date. Port of `_BaptismsByMonthView`
/// (apps/viewer/lib/views/baptisms_by_month_view.dart). Adds a stake-wide unit filter on top of the
/// reusable `BaptismsCard` (which owns the YTD / 12 mo / 24 mo / All window + chart + by-unit drill).
struct BaptismsByMonthView: View {
    let rows: [Member]

    @State private var unit: String?          // nil = whole stake
    @State private var drill: DrillPayload?

    private var units: [String] {
        Array(Set(rows.compactMap { $0.unitName }.filter { !$0.isEmpty })).sorted()
    }
    private var scoped: [Member] {
        guard let unit else { return rows }
        return rows.filter { $0.unitName == unit }
    }
    private var baptized: [Member] { scoped.filter { !$0.isInvestigator } }
    private var allUnits: Set<String> { Set(scoped.map { $0.unitName ?? "—" }) }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                HStack(alignment: .top) {
                    BigHeader(title: "Baptisms by Month", subtitle: "Baptized & confirmed converts",
                              accent: DashboardTab.byMonth.accent)
                    if units.count > 1 {
                        Menu {
                            Button("All units") { unit = nil }
                            ForEach(units, id: \.self) { u in Button(u) { unit = u } }
                        } label: {
                            HStack(spacing: 2) {
                                Text(unit ?? "All units").font(.caption)
                                Image(systemName: "chevron.down").font(.caption2)
                            }
                        }
                    }
                }

                BaptismsCard(baptized: baptized, allUnits: allUnits, onDrill: { drill = $0 })
            }
            .padding(16)
            .frame(maxWidth: 640)
            .frame(maxWidth: .infinity)
        }
        .sheet(item: $drill) { d in
            KpiDrillSheet(title: d.title, events: d.events, allUnits: d.allUnits, bucketLabel: d.bucketLabel)
        }
    }
}
#endif
