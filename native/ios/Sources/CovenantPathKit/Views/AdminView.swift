#if canImport(UIKit)
import SwiftUI

/// Admin · Ops console (port of `admin_page.dart`): independent panels for system health, data
/// freshness, maintenance dispatch, tools/links, diagnostics, admin management, enrolled stakes
/// (per-stake ops), and GitHub Actions runs + changelog. Each panel loads on its own; the broker
/// gates everything to app_admins server-side.
struct AdminView: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(\.appServices) private var services
    @State private var store: AdminStore?
    @State private var me = ""
    @State private var showInviteAdmin = false
    @State private var inviteAdminEmail = ""
    @State private var confirm: ConfirmAction?

    /// A confirm-gated per-stake action (sync / revoke / wipe / remove) — copy mirrors the web ops console.
    private struct ConfirmAction: Identifiable {
        let id = UUID()
        let title: String
        let message: String
        let confirmLabel: String
        let action: () -> Void
    }

    var body: some View {
        NavigationStack {
            Group {
                if let store {
                    content(store)
                } else {
                    ProgressView()
                }
            }
            .navigationTitle("Admin · Ops console")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) { Button("Done") { dismiss() } }
                ToolbarItem(placement: .topBarTrailing) {
                    Button { Task { await store?.loadAll() } } label: { Image(systemName: "arrow.clockwise") }
                        .disabled(store?.busy ?? true)
                }
            }
            .task {
                if store == nil, let services {
                    let s = AdminStore(services: services)
                    store = s
                    await s.loadAll()
                    me = (await services.auth.currentEmail)?.lowercased() ?? ""
                }
            }
        }
    }

    @ViewBuilder
    private func content(_ store: AdminStore) -> some View {
        ScrollView {
            VStack(spacing: 12) {
                healthCard(store)
                freshnessCard(store)
                maintenanceCard(store)
                linksCard(store)
                diagnosticsCard(store)
                // Section order mirrors the web ops console: Admins at #3, then Enrolled stakes.
                adminsCard(store)
                enrolledStakesCard(store)
                runsCard(store)
                changelogCard(store)
            }
            .padding(12)
        }
        .overlay {
            if store.busy {
                ZStack {
                    Color.black.opacity(0.2).ignoresSafeArea()
                    ProgressView()
                }
            }
        }
        .alert("", isPresented: Binding(get: { store.toast != nil }, set: { if !$0 { store.toast = nil } })) {
            Button("OK") { store.toast = nil }
        } message: { Text(store.toast ?? "") }
        .alert(confirm?.title ?? "",
               isPresented: Binding(get: { confirm != nil }, set: { if !$0 { confirm = nil } }),
               presenting: confirm) { c in
            Button(c.confirmLabel, role: .destructive) { c.action() }
            Button("Cancel", role: .cancel) {}
        } message: { c in
            Text(c.message)
        }
        .alert("Invite an admin", isPresented: $showInviteAdmin) {
            TextField("name@example.com", text: $inviteAdminEmail)
                .textInputAutocapitalization(.never).keyboardType(.emailAddress)
            Button("Cancel", role: .cancel) { inviteAdminEmail = "" }
            Button("Invite") {
                let e = inviteAdminEmail.trimmingCharacters(in: .whitespaces)
                inviteAdminEmail = ""
                if !e.isEmpty { Task { await store.inviteAdmin(e) } }
            }
        }
    }

    // MARK: - panels

    private func panel<Content: View>(_ title: String, error: String?,
                                      hasData: Bool, @ViewBuilder content: @escaping () -> Content) -> some View {
        SectionCard(title: hasData || error != nil ? title : "\(title)…") {
            if let error {
                Text("Couldn't load: \(error)").font(.footnote).foregroundStyle(.secondary)
            } else if hasData {
                content()
            } else {
                CardSkeleton(lines: 3)
            }
        }
    }

    private func healthCard(_ s: AdminStore) -> some View {
        panel("System health", error: s.summaryError, hasData: s.summary != nil) {
            let sum = s.summary ?? [:]
            let brokerOk = ((sum["broker"] as? [String: Any])?["ok"] as? Bool) == true
            let sb = (sum["supabase"] as? [String: Any]) ?? [:]
            let sbOk = (sb["ok"] as? Bool) == true
            let gh = (sum["github_configured"] as? Bool) == true
            FlowLayout(spacing: 10, lineSpacing: 10) {
                StatusPill(label: "Broker", ok: brokerOk)
                StatusPill(label: "Supabase", ok: sbOk)
                StatusPill(label: "GitHub Actions", ok: gh, offText: "not linked")
            }
        }
    }

    private func freshnessCard(_ s: AdminStore) -> some View {
        panel("Data freshness", error: s.summaryError, hasData: s.summary != nil) {
            let sb = (s.summary?["supabase"] as? [String: Any]) ?? [:]
            VStack(alignment: .leading, spacing: 8) {
                kv("Last member update", Freshness.ago(sb["last_member_update"] as? String))
                kv("Last stake sync", Freshness.ago(sb["last_stake_sync"] as? String))
                Divider()
                FlowLayout(spacing: 18, lineSpacing: 8) {
                    statTile("Members", sb["members"])
                    statTile("Units", sb["units"])
                    statTile("Stakes", sb["stakes"])
                    statTile("Admins", sb["admins"])
                }
            }
        }
    }

    private func maintenanceCard(_ s: AdminStore) -> some View {
        panel("Maintenance", error: s.summaryError, hasData: s.summary != nil) {
            let on = (s.summary?["github_configured"] as? Bool) == true
            VStack(alignment: .leading, spacing: 10) {
                Text("Each flow re-scrapes LCR (required for fresh data); the choice controls where it writes.")
                    .font(.footnote).foregroundStyle(.secondary)
                FlowLayout(spacing: 10, lineSpacing: 10) {
                    maintBtn("Full sync", ["targets": "both"], on, prominent: true)
                    maintBtn("Supabase only", ["targets": "supabase"], on)
                    maintBtn("Sheets only", ["targets": "sheets"], on)
                    maintBtn("Refresh photos", ["targets": "supabase", "photos": "true"], on)
                }
                if !on {
                    Text("Link GitHub (set GITHUB_TOKEN on the broker) to enable flows.")
                        .font(.caption).foregroundStyle(.secondary)
                }
            }
        }
    }

    @ViewBuilder
    private func maintBtn(_ label: String, _ inputs: [String: Any], _ enabled: Bool, prominent: Bool = false) -> some View {
        let btn = Button {
            Task { await store?.dispatch(label: label, inputs: inputs) }
        } label: { Text(label).font(.callout) }
        .disabled(!enabled)
        btn.cpGlassButton(prominent: prominent)
    }

    private func linksCard(_ s: AdminStore) -> some View {
        let links = ((s.summary?["links"] as? [String: Any]) ?? [:])
            .compactMapValues { $0 as? String }
        return Group {
            if !links.isEmpty {
                SectionCard(title: "Tools & dashboards") {
                    FlowLayout(spacing: 8, lineSpacing: 8) {
                        ForEach(links.sorted(by: { $0.key < $1.key }), id: \.key) { k, v in
                            if let url = URL(string: v) {
                                Link(destination: url) {
                                    Label(k, systemImage: "arrow.up.right.square").font(.caption)
                                        .padding(.horizontal, 10).padding(.vertical, 5)
                                        .background(Color(.tertiarySystemFill), in: Capsule())
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    private func diagnosticsCard(_ s: AdminStore) -> some View {
        panel("Diagnostics", error: s.diagnosticsError, hasData: s.diagnostics != nil) {
            let runs = (s.diagnostics?["runs"] as? [[String: Any]]) ?? []
            let run = runs.first { ($0["kind"] as? String) == "sync" }
            if let run {
                let p = (run["payload"] as? [String: Any]) ?? [:]
                let req = (p["requests"] as? [String: Any]) ?? [:]
                let stats = (p["run_stats"] as? [String: Any]) ?? [:]
                let failed = (stats["failed_units"] as? [Any]) ?? []
                let successPct = (req["success_pct"] as? NSNumber)?.doubleValue ?? 100
                VStack(alignment: .leading, spacing: 10) {
                    FlowLayout(spacing: 10, lineSpacing: 10) {
                        StatusPill(label: "Requests \(Int(successPct))%", ok: successPct >= 99)
                        StatusPill(label: "Units \(stats["units"].map { "\($0)" } ?? "—") ok",
                                   ok: failed.isEmpty, offText: "\(failed.count) failed")
                        StatusPill(label: "\(req["total_errors"].map { "\($0)" } ?? "0") request errors",
                                   ok: ((req["total_errors"] as? NSNumber)?.intValue ?? 0) == 0)
                    }
                    if !failed.isEmpty {
                        Text("Failed units: \(failed.map { "\($0)" }.joined(separator: ", "))")
                            .font(.footnote).foregroundStyle(.orange)
                    }
                    let endpoints = (req["endpoints"] as? [[String: Any]]) ?? []
                    if !endpoints.isEmpty {
                        EndpointPerfView(endpoints: endpoints)
                    }
                }
            } else {
                Text("No sync diagnostics yet.").foregroundStyle(.secondary)
            }
        }
    }

    private func enrolledStakesCard(_ s: AdminStore) -> some View {
        panel("Enrolled stakes", error: s.stakesError, hasData: s.stakes != nil) {
            let stakes = s.stakes ?? []
            if stakes.isEmpty {
                Text("No stakes yet.").foregroundStyle(.secondary)
            } else {
                VStack(spacing: 0) {
                    ForEach(Array(stakes.enumerated()), id: \.offset) { i, st in
                        if i > 0 { Divider().padding(.vertical, 8) }
                        stakeRow(st)
                    }
                }
            }
        }
    }

    @ViewBuilder
    private func stakeRow(_ st: [String: Any]) -> some View {
        let cred = st["credential"] as? [String: Any]
        let name = st["name"] as? String ?? "—"
        let stakeID = "\(st["stake_id"] ?? "")"
        let unitNumber = (st["unit_number"] as? NSNumber)?.intValue
        let jobs7d = (st["jobs_7d"] as? NSNumber)?.intValue ?? 0
        let members = (st["member_count"] as? NSNumber)?.intValue ?? 0
        let running = (st["sync_state"] as? String) == "running"
        let credState = cred == nil ? "none" : ((cred?["state"] as? String) ?? "")
        let lastError = (cred?["last_error"] as? String) ?? ""
        let (credLabel, credColor) = credTag(cred)

        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(name).fontWeight(.semibold)
                // Stable LCR stake ID — stakes get renamed, so the ID is how you identify them (#9).
                if let unit = unitNumber {
                    Text("ID \(unit)").font(.caption).monospaced().foregroundStyle(.secondary)
                }
                Spacer()
                if running { ProgressView().controlSize(.mini) }
                if !running, credState != "revoked", credState != "none" {
                    Button {
                        confirm = ConfirmAction(
                            title: "Sync \(name) now?",
                            message: "Re-scrapes LCR for this one stake and writes to Supabase. Runs in the cloud (GitHub Actions) and takes a few minutes.",
                            confirmLabel: "Sync") {
                                Task { await store?.syncStake(unitNumber: "\(st["unit_number"] ?? "")", name: name) }
                            }
                    } label: {
                        Image(systemName: "arrow.triangle.2.circlepath")
                    }
                }
                if credState == "active" || credState == "stale" {
                    Button(role: .destructive) {
                        confirm = ConfirmAction(
                            title: "Revoke sync for \(name)?",
                            message: "Daily sync for this stake will stop until a leader re-enrolls. You can do this to support a stake whose credential is stale or compromised.",
                            confirmLabel: "Revoke") {
                                Task { await store?.revokeStake(stakeID: stakeID, name: name) }
                            }
                    } label: {
                        Image(systemName: "link.badge.plus")
                    }
                }
                Button {
                    confirm = ConfirmAction(
                        title: "Wipe \(name)'s data?",
                        message: "Deletes ALL of this stake's member records — but KEEPS the stake, its leaders' access, and the sync credential. The data re-populates on the next sync. Use this to clear out bad or partial data.",
                        confirmLabel: "Wipe data") {
                            Task { await store?.wipeStakeData(stakeID: stakeID, name: name) }
                        }
                } label: {
                    Text("Wipe").font(.caption.weight(.semibold)).foregroundStyle(Color(hex: 0xE65100))
                }
                Button {
                    confirm = ConfirmAction(
                        title: "Permanently remove \(name)?",
                        message: "DELETES EVERYTHING for this stake — the sync credential, ALL member data, every leader's access role, and the stake itself, as if it never onboarded. This CANNOT be undone.",
                        confirmLabel: "Remove everything") {
                            Task { await store?.removeStake(stakeID: stakeID, name: name) }
                        }
                } label: {
                    Text("Remove").font(.caption.weight(.semibold)).foregroundStyle(Color(hex: 0xC62828))
                }
            }
            FlowLayout(spacing: 8, lineSpacing: 4) {
                StatusTag(credLabel, color: credColor)
                Text("\(members) members").font(.caption).foregroundStyle(.secondary)
                Text("· synced \(Freshness.ago(st["last_synced_at"] as? String))").font(.caption).foregroundStyle(.secondary)
                // Sync jobs that ran for this stake in the last 7 days (#9). Amber when none ran.
                Text("· \(jobs7d) job\(jobs7d == 1 ? "" : "s")/7d")
                    .font(.caption).foregroundStyle(jobs7d == 0 ? .orange : .secondary)
                if let p = cred?["principal_name"] as? String {
                    Text("· by \(p)").font(.caption).foregroundStyle(.secondary)
                }
            }
            if let cred {
                // Authorization cadence (mirrors web): when it was last authorized, whether it can
                // self-renew (refresh token captured at enroll), and how often re-auth actually happened.
                Text(cadenceLine(cred))
                    .font(.caption).foregroundStyle(.secondary)
            }
            if credState == "stale" {
                Text("Last sync failed\(lastError.isEmpty ? "" : ": \(lastError.prefix(120))") — a leader must re-authorize (or take over).")
                    .font(.caption).foregroundStyle(AppColors.danger)
            }
            if let missing = cred?["missing"] as? [Any], !missing.isEmpty, (cred?["complete"] as? Bool) != true {
                Text("Missing: \(missing.map { "\($0)" }.joined(separator: ", "))")
                    .font(.caption).foregroundStyle(.orange)
            }
        }
    }

    /// Admin-style "ago" with "never" for a missing timestamp (mirrors web `agoOrNever`).
    private func agoOrNever(_ iso: Any?) -> String {
        guard let s = iso as? String, !s.isEmpty else { return "never" }
        return Freshness.ago(s)
    }

    /// "authorized <ago> · self-renewing | manual re-auth needed when session expires · N re-auths/30d"
    /// from enrolled-stakes `self_renewing` + `reauths_30d` (mirrors the web cadence line).
    private func cadenceLine(_ cred: [String: Any]) -> String {
        let selfRenewing = cred["self_renewing"] as? Bool
        let reauths = (cred["reauths_30d"] as? NSNumber)?.intValue ?? 0
        var line = "authorized \(agoOrNever(cred["updated_at"]))"
        if let selfRenewing {
            line += selfRenewing ? " · self-renewing" : " · manual re-auth needed when session expires"
        }
        line += " · \(reauths) re-auth\(reauths == 1 ? "" : "s")/30d"
        return line
    }

    private func credTag(_ cred: [String: Any]?) -> (String, Color) {
        guard let cred else { return ("No credential", AppColors.neutral) }
        if (cred["state"] as? String) == "revoked" { return ("Revoked", AppColors.warning) }
        if (cred["state"] as? String) == "stale" { return ("Stale · needs re-auth", AppColors.danger) }
        if (cred["complete"] as? Bool) == true { return ("Active · full coverage", AppColors.success) }
        return ("Active · partial", AppColors.info)
    }

    private func runsCard(_ s: AdminStore) -> some View {
        panel("GitHub Actions", error: s.actionsError, hasData: s.actions != nil) {
            let configured = (s.actions?["configured"] as? Bool) == true
            let runs = (s.actions?["runs"] as? [[String: Any]]) ?? []
            if !configured {
                Text("Set GITHUB_TOKEN on the broker (Actions: read & write, Contents: read) to enable runs + the changelog. The rest of the console still works.")
                    .font(.footnote).foregroundStyle(.secondary)
            } else if runs.isEmpty {
                Text("No runs found.").foregroundStyle(.secondary)
            } else {
                VStack(spacing: 0) {
                    ForEach(Array(runs.enumerated()), id: \.offset) { i, r in
                        if i > 0 { Divider() }
                        runRow(r)
                    }
                }
            }
        }
    }

    @ViewBuilder
    private func runRow(_ r: [String: Any]) -> some View {
        let status = r["status"] as? String ?? ""
        let conclusion = r["conclusion"] as? String ?? ""
        let inProgress = status == "in_progress" || status == "queued"
        HStack(spacing: 10) {
            runIcon(status: status, conclusion: conclusion)
            VStack(alignment: .leading) {
                Text("\(r["name"] as? String ?? "") #\(r["run_number"].map { "\($0)" } ?? "")")
                Text("\(r["event"] as? String ?? "") · \(Freshness.ago(r["created_at"] as? String))\(durLabel(r, status: status))")
                    .font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            if inProgress {
                ProgressView().controlSize(.mini)
            } else if let id = (r["id"] as? NSNumber)?.intValue {
                Button { Task { await store?.rerun(id) } } label: { Image(systemName: "arrow.clockwise") }
            }
        }
        .padding(.vertical, 4)
    }

    /// " · took 2m 13s" / " · running 45s" suffix for a run, or "" when duration is unknown.
    private func durLabel(_ r: [String: Any], status: String) -> String {
        let d = Freshness.dur(r["duration_seconds"])
        guard !d.isEmpty else { return "" }
        return " · \(status == "completed" ? "took" : "running") \(d)"
    }

    private func runIcon(status: String, conclusion: String) -> some View {
        if status != "completed" {
            return Image(systemName: "hourglass").foregroundStyle(AppColors.info)
        }
        let ok = conclusion == "success"
        return Image(systemName: ok ? "checkmark.circle.fill" : "xmark.circle.fill")
            .foregroundStyle(ok ? AppColors.success : AppColors.danger)
    }

    private func changelogCard(_ s: AdminStore) -> some View {
        let configured = (s.actions?["configured"] as? Bool) == true
        let commits = (s.actions?["commits"] as? [[String: Any]]) ?? []
        return Group {
            if configured && !commits.isEmpty {
                SectionCard(title: "Changelog") {
                    VStack(spacing: 0) {
                        ForEach(Array(commits.enumerated()), id: \.offset) { i, c in
                            if i > 0 { Divider() }
                            HStack(spacing: 10) {
                                Image(systemName: "arrow.triangle.branch").font(.caption)
                                VStack(alignment: .leading) {
                                    Text("\(c["message"] as? String ?? "")").lineLimit(2)
                                    Text("\(c["sha"] as? String ?? "") · \(c["author"] as? String ?? "") · \(Freshness.ago(c["date"] as? String))")
                                        .font(.caption).foregroundStyle(.secondary)
                                }
                                Spacer()
                            }
                            .padding(.vertical, 4)
                        }
                    }
                }
            }
        }
    }

    private func adminsCard(_ s: AdminStore) -> some View {
        panel("Admins", error: s.adminsError, hasData: s.admins != nil) {
            VStack(spacing: 0) {
                HStack {
                    Spacer()
                    Button { showInviteAdmin = true } label: {
                        Label("Invite", systemImage: "person.badge.plus").font(.callout)
                    }
                }
                ForEach(s.admins ?? []) { a in
                    Divider()
                    HStack(spacing: 10) {
                        Image(systemName: "shield")
                        VStack(alignment: .leading) {
                            Text(a.email)
                            if let by = a.invitedByEmail { Text("invited by \(by)").font(.caption).foregroundStyle(.secondary) }
                        }
                        Spacer()
                        if a.email.lowercased() == me {
                            Text("you").font(.caption).padding(.horizontal, 8).padding(.vertical, 2)
                                .background(Color(.tertiarySystemFill), in: Capsule())
                        } else {
                            Button(role: .destructive) { Task { await store?.revokeAdmin(a.email) } } label: {
                                Image(systemName: "minus.circle")
                            }
                        }
                    }
                    .padding(.vertical, 4)
                }
            }
        }
    }

    // MARK: - small helpers

    private func kv(_ k: String, _ v: String) -> some View {
        HStack { Text(k); Spacer(); Text(v).fontWeight(.medium) }
    }
    private func statTile(_ label: String, _ v: Any?) -> some View {
        VStack { Text(v.map { "\($0)" } ?? "—").font(.title2.bold()); Text(label).font(.caption) }
    }
}

/// #13–15: endpoint metrics grouped by route (defensive client-side normalization so even OLD
/// diagnostics rows collapse), failing endpoints first, with a "Failing only / All" toggle.
private struct EndpointPerfView: View {
    let endpoints: [[String: Any]]
    @State private var failingOnly = true

    private struct Row: Identifiable {
        let id = UUID(); let endpoint: String; let calls: Int; let errors: Int; let avgMs: Int
    }

    private static func norm(_ ep: String) -> String {
        ep.split(separator: "/", omittingEmptySubsequences: false).map { seg -> String in
            let s = String(seg)
            if s == "{id}" { return "{id}" }
            if !s.isEmpty, s.allSatisfy({ $0.isNumber }) { return "{id}" }
            let hex = s.hasPrefix("{id}") ? String(s.dropFirst(4)) : s
            if hex.count >= 8, hex.allSatisfy({ $0.isHexDigit }) { return "{id}" }
            return s
        }.joined(separator: "/")
    }

    private var grouped: [Row] {
        var by: [String: (calls: Int, errors: Int, ms: Int)] = [:]
        for ep in endpoints {
            let key = Self.norm(ep["endpoint"] as? String ?? "")
            let calls = (ep["calls"] as? NSNumber)?.intValue ?? 0
            let avg = (ep["avg_ms"] as? NSNumber)?.intValue ?? 0
            var g = by[key] ?? (0, 0, 0)
            g.calls += calls
            g.errors += (ep["errors"] as? NSNumber)?.intValue ?? 0
            g.ms += avg * calls
            by[key] = g
        }
        return by.map { Row(endpoint: $0.key, calls: $0.value.calls, errors: $0.value.errors,
                            avgMs: $0.value.calls > 0 ? $0.value.ms / $0.value.calls : 0) }
            .sorted { ($0.errors, $0.calls) > ($1.errors, $1.calls) }
    }

    var body: some View {
        let g = grouped
        let failing = g.filter { $0.errors > 0 }
        let shown = (failingOnly && !failing.isEmpty) ? failing : g
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text("Endpoint performance").font(.subheadline.bold())
                Spacer()
                if !failing.isEmpty {
                    Button(failingOnly ? "Show all \(g.count)" : "Failing only (\(failing.count))") {
                        failingOnly.toggle()
                    }.font(.caption)
                }
            }
            ForEach(shown) { ep in
                HStack {
                    Text(ep.endpoint).font(.system(.caption, design: .monospaced)).lineLimit(1)
                    Spacer()
                    Text("\(ep.calls) calls · \(ep.avgMs)ms\(ep.errors != 0 ? " · \(ep.errors) err" : "")")
                        .font(.caption).foregroundStyle(ep.errors != 0 ? Color.red : Color.secondary)
                }
            }
        }
    }
}
#endif
