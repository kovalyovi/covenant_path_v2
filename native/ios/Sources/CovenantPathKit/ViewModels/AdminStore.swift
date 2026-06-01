import Foundation
import Observation

/// Loads the Admin/Ops console panels independently (port of `_AdminPageState`): each panel has its
/// own loadable so a slow/failed section (e.g. GitHub Actions) only spins/errors in its own card.
/// The broker verifies the caller is an app_admin server-side (admin-gated).
@MainActor
@Observable
public final class AdminStore {

    public private(set) var summary: [String: Any]?
    public private(set) var summaryError: String?
    public private(set) var diagnostics: [String: Any]?
    public private(set) var diagnosticsError: String?
    public private(set) var actions: [String: Any]?
    public private(set) var actionsError: String?
    public private(set) var stakes: [[String: Any]]?
    public private(set) var stakesError: String?
    public private(set) var admins: [AppAdmin]?
    public private(set) var adminsError: String?

    public var busy = false
    public var toast: String?

    private let services: AppServices
    private var broker: BrokerService { services.broker }

    public init(services: AppServices) { self.services = services }

    public func loadAll() async {
        await withTaskGroup(of: Void.self) { group in
            group.addTask { await self.loadSummary() }
            group.addTask { await self.loadDiagnostics() }
            group.addTask { await self.loadActions() }
            group.addTask { await self.loadStakes() }
            group.addTask { await self.loadAdmins() }
        }
    }

    func loadSummary() async {
        do { summary = try await broker.adminSummary(); summaryError = nil }
        catch { summaryError = error.localizedDescription }
    }
    func loadDiagnostics() async {
        do { diagnostics = try await broker.adminDiagnostics(); diagnosticsError = nil }
        catch { diagnosticsError = error.localizedDescription }
    }
    func loadActions() async {
        do { actions = try await broker.adminActions(); actionsError = nil }
        catch { actionsError = error.localizedDescription }
    }
    func loadStakes() async {
        do {
            let r = try await broker.adminEnrolledStakes()
            stakes = (r["stakes"] as? [[String: Any]]) ?? []
            stakesError = nil
        } catch { stakesError = error.localizedDescription }
    }
    func loadAdmins() async {
        do { admins = try await services.gateway.appAdmins(); adminsError = nil }
        catch { adminsError = error.localizedDescription }
    }

    // MARK: - actions (each guarded; sets a toast)

    private func guarded(_ action: @escaping () async throws -> String) async {
        busy = true
        do { toast = try await action() }
        catch { toast = error.localizedDescription }
        busy = false
    }

    public func dispatch(label: String, inputs: [String: Any]) async {
        await guarded {
            _ = try await self.broker.adminRun("daily-sync.yml", inputs: inputs)
            await self.loadActions()
            return "\(label) dispatched. Refresh in a minute to see the run."
        }
    }

    public func rerun(_ id: Int) async {
        await guarded {
            _ = try await self.broker.adminRerun(id)
            await self.loadActions()
            return "Re-run requested for #\(id)."
        }
    }

    public func syncStake(unitNumber: String, name: String) async {
        guard !unitNumber.isEmpty, unitNumber != "null" else {
            toast = "No unit number on file for \(name) — can't scope a sync."; return
        }
        await guarded {
            _ = try await self.broker.adminRun("daily-sync.yml", inputs: ["stake": unitNumber, "targets": "supabase"])
            await self.loadStakes()
            return "Sync dispatched for \(name). Refresh in a minute to see the run."
        }
    }

    public func revokeStake(stakeID: String, name: String) async {
        await guarded {
            _ = try await self.broker.adminRevokeStake(stakeID)
            await self.loadStakes()
            return "Revoked sync for \(name)."
        }
    }

    public func inviteAdmin(_ email: String) async {
        await guarded {
            let res = try await self.broker.adminInvite(email)
            await self.loadAdmins()
            let status = res["status"] as? String ?? ""
            switch status {
            case "already_admin": return "\(email) is already an admin."
            case "pending_owner_approval": return "Request sent — the owner must approve \(email) by email."
            default: return "\(email): \(status)"
            }
        }
    }

    public func revokeAdmin(_ email: String) async {
        await guarded {
            try await self.services.gateway.revokeAdmin(email: email)
            await self.loadAdmins()
            return "Revoked \(email)."
        }
    }
}
