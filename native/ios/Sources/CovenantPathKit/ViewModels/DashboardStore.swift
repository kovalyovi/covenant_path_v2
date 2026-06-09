import Foundation
import Observation

/// Loads the single-stake dataset the whole dashboard reads + the surrounding shell state (admin
/// flag, enrollment status, syncing/stale banners, missionaries, freshness). Faithful port of
/// `_DashboardPageState`: `_bootstrap`/`_loadStakes`/`_applyCurrentStake`/`_load`/`_switchStake`/
/// `_checkAdmin`/`_loadEnrollStatus`/`_syncNow`.
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

    public private(set) var isAdmin = false
    public private(set) var enrollStatus: EnrollmentStatus?

    /// Optimistic syncing flag (set right after a Sync-now; reconciled from stakes.sync_state).
    public private(set) var syncing = false
    public private(set) var syncStartedAt: Date?
    private var syncPollTask: Task<Void, Never>? // N3: re-checks sync_state every ~5s while syncing

    private let services: AppServices
    private var repo: MembersRepository { services.members }

    public init(services: AppServices) { self.services = services }

    // MARK: - derived shell state

    public var currentStake: Stake? {
        guard let id = currentStakeID else { return stakes.first }
        return stakes.first { $0.id == id } ?? stakes.first
    }

    public var stakeName: String { currentStake?.name ?? "Covenant Path" }
    public var lastSyncedAt: String? { currentStake?.lastSyncedAt }

    /// Unit-name → missionaries for the current stake (drives the per-unit missionary strip).
    public var missionariesByUnit: [String: [Missionary]] { currentStake?.missionaries ?? [:] }

    /// Show the stale-credential banner when the stake's sync credential was revoked OR went stale
    /// (its delegated Church session died → daily sync is failing until a leader re-authorizes).
    public var staleCredential: Bool {
        enrollStatus?.credential.isRevoked == true || enrollStatus?.credential.isStale == true
    }

    public var brokerAvailable: Bool { services.broker.available }

    public var newMembers: [Member] { members.filter { !$0.isInvestigator } }
    public var investigators: [Member] { members.filter { $0.isInvestigator } }

    // MARK: - bootstrap

    /// Initial bootstrap: admin check + stakes (to pick the scope), then that stake's members.
    public func load() async {
        state = .loading
        Task { await self.checkAdmin() }
        do {
            try await loadStakes()
            try await reloadMembers()
            state = .loaded
            // #11: prefetch enrollment status in the background (not awaited) so opening Sync settings
            // is instant; it's also needed for the empty state.
            Task { await self.loadEnrollStatus() }
        } catch {
            state = .failed(error.localizedDescription)
        }
    }

    /// Pull-to-refresh / Refresh action: re-fetch stakes (freshness, banner) then members.
    public func refresh() async {
        do {
            try await loadStakes()
            try await reloadMembers()
            state = .loaded
            if members.isEmpty { await loadEnrollStatus() }
        } catch {
            state = .failed(error.localizedDescription)
        }
    }

    public func selectStake(_ id: String) async {
        guard id != currentStakeID else { return }
        currentStakeID = id
        AppPrefs.setString(AppPrefs.currentStake, id)
        applyCurrentStake()
        state = .loading
        do {
            try await reloadMembers()
            state = .loaded
        } catch {
            state = .failed(error.localizedDescription)
        }
    }

    private func loadStakes() async throws {
        let fetched = try await repo.stakes()
        stakes = fetched
        // Keep the remembered choice if still visible; else default to the freshest stake.
        if currentStakeID == nil {
            currentStakeID = AppPrefs.string(AppPrefs.currentStake)
        }
        if currentStakeID == nil || !fetched.contains(where: { $0.id == currentStakeID }) {
            currentStakeID = fetched.first?.id
        }
        applyCurrentStake()
    }

    /// Recompute syncing state from the selected stake only (port of `_applyCurrentStake`).
    private func applyCurrentStake() {
        guard let s = currentStake else { return }
        if s.isSyncing {
            syncing = true
            syncStartedAt = Freshness.parse(s.syncStartedAt)
        } else if !optimisticSync {
            syncing = false
            syncStartedAt = nil
        }
        startSyncPollIfNeeded()
    }

    /// N3: while a sync runs, re-check stakes.sync_state every ~5s so the "syncing…" banner
    /// self-clears and fresh members load without a manual refresh. `optimisticSync` keeps the
    /// banner up during the brief window before the backend marks the run "running"; the loop ends
    /// when syncing turns false (incl. the 30-min crashed-run guard in `Stake.isSyncing`). The weak
    /// self loop also ends naturally if the store is deallocated.
    private func startSyncPollIfNeeded() {
        guard syncing, syncPollTask == nil else { return }
        syncPollTask = Task { [weak self] in
            while self?.syncing == true && !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 5 * 1_000_000_000)
                if Task.isCancelled { break }
                try? await self?.loadStakes() // recomputes syncing via applyCurrentStake
            }
            try? await self?.reloadMembers() // sync finished → pull the fresh members
            self?.syncPollTask = nil
        }
    }

    private var optimisticSync = false

    private func reloadMembers() async throws {
        guard let id = currentStakeID else { members = []; return }
        members = try await repo.members(stakeID: id)
    }

    private func checkAdmin() async {
        let v = await services.gateway.isAdmin()
        isAdmin = v
    }

    public func loadEnrollStatus() async {
        guard services.broker.available else { return }
        enrollStatus = try? await services.broker.enrollmentStatus()
    }

    // MARK: - sync now (provider) — port of `_syncNow`

    public struct SyncResult { public let started: Bool; public let partial: Bool; public let message: String }

    @discardableResult
    public func syncNow() async -> SyncResult {
        do {
            let res = try await services.broker.syncNow()
            let partial = (res["coverage_complete"] as? Bool) == false
            // Optimistically show in-progress right away; reconcile after a delay.
            optimisticSync = true
            syncing = true
            syncStartedAt = Date()
            startSyncPollIfNeeded()
            Task { [weak self] in
                try? await Task.sleep(nanoseconds: 8 * 1_000_000_000)
                self?.optimisticSync = false
                try? await self?.loadStakes()
            }
            let msg = partial
                ? "Sync started — note: your calling can't pull every field, so some data stays blank. Takes a few minutes."
                : "Sync started for your stake — this takes a few minutes."
            return SyncResult(started: true, partial: partial, message: msg)
        } catch {
            return SyncResult(started: false, partial: false,
                              message: "Couldn't start sync: \(error.localizedDescription)")
        }
    }
}
