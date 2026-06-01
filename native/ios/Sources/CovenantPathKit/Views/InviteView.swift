#if canImport(UIKit)
import SwiftUI

/// Power users (port of `invite_page.dart`): list current invites (grouped by email), invite by
/// email with an optional unit scope (rpc invite_power_user), and revoke (rpc revoke_power_user).
struct InviteView: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(\.appServices) private var services

    @State private var email = ""
    @State private var unitID: String?
    @State private var units: [UnitRow] = []
    @State private var invites: [Invitation] = []
    @State private var loaded = false
    @State private var busy = false
    @State private var message: String?
    @State private var ok = false

    private var gateway: SupabaseGateway? { services?.gateway }

    var body: some View {
        NavigationStack {
            List {
                Section {
                    Text("Give someone your exact access. They sign in with the invited email (a one-time code is sent — no Church account needed), see what you see, and can invite others.")
                        .font(.footnote).foregroundStyle(.secondary)
                    if units.count > 1 {
                        Picker("Access to", selection: $unitID) {
                            Text("Everything I can see").tag(String?.none)
                            ForEach(units) { u in Text("\(u.name ?? "") only").tag(String?.some(u.id)) }
                        }
                    }
                    HStack {
                        TextField("Email to invite", text: $email)
                            .textContentType(.emailAddress).keyboardType(.emailAddress)
                            .textInputAutocapitalization(.never).autocorrectionDisabled()
                        Button("Invite") { Task { await invite() } }
                            .disabled(busy || email.trimmingCharacters(in: .whitespaces).isEmpty)
                    }
                    if let message {
                        Text(message).font(.footnote)
                            .foregroundStyle(ok ? StatusColor.done : .red)
                    }
                }

                Section("Power users") {
                    if !loaded {
                        CardSkeleton(lines: 3)
                    } else if grouped.isEmpty {
                        Text("No power users invited yet.").foregroundStyle(.secondary)
                    } else {
                        ForEach(grouped) { inv in
                            HStack {
                                Image(systemName: inv.isRevoked ? "person.slash" : "person")
                                VStack(alignment: .leading) {
                                    Text(inv.invitedEmail ?? "—")
                                    Text("\(inv.role ?? "") • \(inv.status ?? "")"
                                         + (inv.invitedByEmail != nil ? " • by \(inv.invitedByEmail!)" : ""))
                                        .font(.caption).foregroundStyle(.secondary)
                                }
                                Spacer()
                                if !inv.isRevoked {
                                    Button("Revoke") { Task { await revoke(inv.invitedEmail ?? "") } }
                                        .font(.callout)
                                }
                            }
                        }
                    }
                }
            }
            .navigationTitle("Power users")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .topBarTrailing) { Button("Done") { dismiss() } } }
            .task { await loadAll() }
        }
    }

    /// Collapse multiple scope rows per email (mirrors invite_page's `byEmail`).
    private var grouped: [Invitation] {
        var seen = Set<String>()
        var out: [Invitation] = []
        for r in invites {
            let key = r.invitedEmail ?? ""
            if seen.insert(key).inserted { out.append(r) }
        }
        return out
    }

    private func loadAll() async {
        guard let gateway else { loaded = true; return }
        units = (try? await gateway.units()) ?? []
        invites = (try? await gateway.invitations()) ?? []
        loaded = true
    }

    private func invite() async {
        guard let gateway else { return }
        let e = email.trimmed
        guard !e.isEmpty else { return }
        busy = true; message = nil
        do {
            let n = try await gateway.invitePowerUser(email: e, unitID: unitID)
            message = "Invited \(e) (\(n) scope\(n == 1 ? "" : "s")). They can sign in with that email."
            ok = true
            email = ""
            invites = (try? await gateway.invitations()) ?? invites
        } catch {
            message = "Could not invite: \(error.localizedDescription)"; ok = false
        }
        busy = false
    }

    private func revoke(_ email: String) async {
        guard let gateway else { return }
        do { try await gateway.revokePowerUser(email: email) } catch {}
        invites = (try? await gateway.invitations()) ?? invites
    }
}
#endif
