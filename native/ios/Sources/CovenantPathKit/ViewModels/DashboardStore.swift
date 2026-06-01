import Foundation
import Observation

/// Loads the single-stake dataset the whole dashboard reads. Mirrors `_bootstrap` / `_loadStakes` /
/// `_load`: resolve which stake to show (freshest the user can see), then fetch its members scoped
/// by `stake_id`. Power users with multiple stakes get a switcher (`selectStake`).
@MainActor
@Observable
public final class DashboardStore {

    public enum LoadState: Equatable {
        case idle
        case loading
        case loaded
        case failed(String)
    }

    public private(set) var state: LoadState = .idle
    public private(set) var stakes: [Stake] = []
    public private(set) var currentStakeID: String?
    public private(set) var members: [Member] = []

    private let repo: MembersRepository

    public init(repo: MembersRepository) { self.repo = repo }

    public var currentStake: Stake? {
        guard let id = currentStakeID else { return stakes.first }
        return stakes.first { $0.id == id } ?? stakes.first
    }

    public var stakeName: String { currentStake?.name ?? "Covenant Path" }
    public var lastSyncedAt: String? { currentStake?.lastSyncedAt }

    /// Unit-name → missionaries for the current stake (drives the per-unit missionary strip).
    public var missionariesByUnit: [String: [Missionary]] {
        currentStake?.missionaries ?? [:]
    }

    // MARK: - derived collections (the sections every tab slices)

    public var newMembers: [Member] { members.filter { !$0.isInvestigator } }
    public var investigators: [Member] { members.filter { $0.isInvestigator } }

    // MARK: - loading

    /// Initial bootstrap: stakes first (to pick the scope), then that stake's members.
    public func load() async {
        state = .loading
        do {
            let fetched = try await repo.stakes()
            stakes = fetched
            if currentStakeID == nil || !fetched.contains(where: { $0.id == currentStakeID }) {
                currentStakeID = fetched.first?.id
            }
            try await reloadMembers()
            state = .loaded
        } catch {
            state = .failed(error.localizedDescription)
        }
    }

    /// Pull-to-refresh: re-fetch members for the current stake (and refresh stake metadata).
    public func refresh() async {
        do {
            stakes = try await repo.stakes()
            try await reloadMembers()
            state = .loaded
        } catch {
            state = .failed(error.localizedDescription)
        }
    }

    public func selectStake(_ id: String) async {
        guard id != currentStakeID else { return }
        currentStakeID = id
        state = .loading
        do {
            try await reloadMembers()
            state = .loaded
        } catch {
            state = .failed(error.localizedDescription)
        }
    }

    private func reloadMembers() async throws {
        guard let id = currentStakeID else { members = []; return }
        members = try await repo.members(stakeID: id)
    }
}
