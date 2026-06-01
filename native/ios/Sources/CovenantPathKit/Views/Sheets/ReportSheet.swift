#if canImport(UIKit)
import SwiftUI

/// Ad-hoc leader report (port of `_generateReport` + `_ReportSheet`): loads the broker `/report`,
/// shows totals + most-needed steps + outstanding-by-member, and an "Email to me" action (`/report/email`).
struct ReportSheet: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(\.appServices) private var services
    let onToast: (String) -> Void

    @State private var report: [String: Any]?
    @State private var loaded = false
    @State private var error: String?

    private var broker: BrokerService? { services?.broker }

    var body: some View {
        NavigationStack {
            Group {
                if !loaded {
                    VStack { ProgressView() }.frame(maxWidth: .infinity, maxHeight: .infinity)
                } else if let report {
                    content(report)
                } else {
                    ContentUnavailableView("Couldn't build report",
                                           systemImage: "doc.text",
                                           description: Text(error ?? "Reports need Church-account login configured."))
                }
            }
            .navigationTitle("Report")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) { Button("Close") { dismiss() } }
                if report != nil {
                    ToolbarItem(placement: .topBarTrailing) {
                        Button { Task { await emailReport() } } label: {
                            Label("Email to me", systemImage: "envelope")
                        }
                    }
                }
            }
            .task { await load() }
        }
        .presentationDetents([.large])
    }

    @ViewBuilder
    private func content(_ r: [String: Any]) -> some View {
        let total = (r["total"] as? NSNumber)?.intValue ?? 0
        let onTrack = (r["on_track"] as? NSNumber)?.intValue ?? 0
        let outstanding = (r["outstanding"] as? [[String: Any]]) ?? []
        let byMilestone = (r["by_milestone"] as? [[Any]]) ?? []

        ScrollView {
            VStack(alignment: .leading, spacing: 8) {
                Text(r["stake_name"] as? String ?? "Convert report").font(.title2.bold())
                Text("\(total) new members · \(onTrack) on track · \(outstanding.count) need attention")
                    .font(.callout).foregroundStyle(.secondary)
                Divider().padding(.vertical, 8)

                if !byMilestone.isEmpty {
                    Text("Most-needed steps").font(.headline)
                    ForEach(Array(byMilestone.enumerated()), id: \.offset) { _, kv in
                        HStack {
                            Text("\(kv.first.map { "\($0)" } ?? "")")
                            Spacer()
                            Text("\(kv.count > 1 ? "\(kv[1])" : "")").fontWeight(.semibold)
                        }
                        .padding(.vertical, 2)
                    }
                    Divider().padding(.vertical, 8)
                }

                if outstanding.isEmpty {
                    Text("Everyone in scope is on track. 🎉")
                        .frame(maxWidth: .infinity).padding(.vertical, 20)
                } else {
                    Text("Outstanding by member").font(.headline)
                    ForEach(Array(outstanding.enumerated()), id: \.offset) { _, o in
                        VStack(alignment: .leading, spacing: 2) {
                            Text("\(o["name"] as? String ?? "")"
                                 + (o["unit"] != nil ? " · \(o["unit"] as? String ?? "")" : ""))
                                .fontWeight(.semibold)
                            Text(((o["missing"] as? [String]) ?? []).joined(separator: ", "))
                                .font(.footnote).foregroundStyle(.secondary)
                        }
                        .padding(.vertical, 4)
                    }
                }
            }
            .padding(20)
        }
    }

    private func load() async {
        guard let broker, broker.available else {
            error = "Reports need Church-account login configured."; loaded = true; return
        }
        do { report = try await broker.report() }
        catch let e { error = "Couldn't build report: \(e.localizedDescription)" }
        loaded = true
    }

    private func emailReport() async {
        guard let broker else { return }
        do {
            let res = try await broker.emailReport()
            dismiss()
            onToast("Report emailed to \(res["to"] as? String ?? "you").")
        } catch {
            onToast("Couldn't email report: \(error.localizedDescription)")
        }
    }
}
#endif
