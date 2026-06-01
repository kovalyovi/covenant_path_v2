#if canImport(UIKit)
import SwiftUI

/// KPIs — lowest priority for the PoC, so this is a labeled stub that still shows a few real,
/// at-a-glance stake metrics (computed from the loaded members) rather than charts. The full Flutter
/// KPIs tab renders line-chart cards (Month/Year/All) with drill-downs; that's intentionally not
/// ported here.
struct KPIsView: View {
    let rows: [Member]

    private var newMembers: [Member] { rows.filter { !$0.isInvestigator } }
    private var investigators: [Member] { rows.filter { $0.isInvestigator } }
    private var avgCompletion: Double { Milestones.averageCompletion(newMembers) }

    /// Average Golden Hour completion per unit (mirrors `_unitCompletion`), high→low.
    private var byUnit: [(unit: String, pct: Double, n: Int)] {
        let groups = Dictionary(grouping: newMembers) { $0.unitName ?? "—" }
        return groups.map { (unit: $0.key, pct: Milestones.averageCompletion($0.value), n: $0.value.count) }
            .sorted { $0.pct > $1.pct }
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                BigHeader(title: "KPIs", subtitle: "Stake metrics (charts stubbed for the PoC)",
                          accent: DashboardTab.kpis.accent)

                SectionCard(title: "At a glance", systemImage: "chart.bar", iconColor: DashboardTab.kpis.accent) {
                    FlowLayout(spacing: 18, lineSpacing: 14) {
                        stat("New members", "\(newMembers.count)")
                        stat("Being taught", "\(investigators.count)")
                        stat("Avg. completion", "\(Int((avgCompletion * 100).rounded()))%")
                    }
                }

                SectionCard(title: "Golden Hour completion by unit",
                            systemImage: "building.2", iconColor: DashboardTab.kpis.accent) {
                    if byUnit.isEmpty {
                        Text("No baptized members yet.").foregroundStyle(.secondary)
                    } else {
                        VStack(spacing: 10) {
                            ForEach(byUnit, id: \.unit) { row in
                                VStack(alignment: .leading, spacing: 4) {
                                    HStack {
                                        Text(row.unit).font(.subheadline)
                                        Spacer()
                                        Text("\(Int((row.pct * 100).rounded()))% · \(row.n)")
                                            .font(.caption).foregroundStyle(.secondary)
                                    }
                                    ProgressView(value: row.pct).tint(DashboardTab.kpis.accent)
                                }
                            }
                        }
                    }
                }

                Label("Time-series charts (Month/Year/All) are not implemented in this PoC.",
                      systemImage: "info.circle")
                    .font(.caption).foregroundStyle(.secondary)
            }
            .padding(16)
            .frame(maxWidth: 760)
            .frame(maxWidth: .infinity)
        }
    }

    private func stat(_ label: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(value).font(.title2.bold())
            Text(label).font(.caption).foregroundStyle(.secondary)
        }
        .frame(width: 120, alignment: .leading)
    }
}
#endif
