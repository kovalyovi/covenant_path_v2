import Foundation
import Supabase

/// Read-only data access to Supabase. RLS does ALL access gating — the app does no filtering of its
/// own (the spec's golden rule), it just `select`s and shows what comes back. Mirrors the Flutter
/// dashboard's `_loadStakes` + `_load`.
public protocol MembersRepository: Sendable {
    /// All stakes the signed-in user can see (RLS-scoped), freshest first.
    func stakes() async throws -> [Stake]
    /// Members for a single stake, ordered by unit name then name (the dashboard's ordering).
    func members(stakeID: String) async throws -> [Member]
}

public struct SupabaseMembersRepository: MembersRepository {
    private let client: SupabaseClient
    public init(client: SupabaseClient) { self.client = client }

    /// The exact column list the Flutter dashboard selects (`dashboard_page.dart` `_columns`).
    static let memberColumns = """
    person_uuid, stake_id, unit_id, name, unit_name, baptism_date, birth_date, \
    membership_duration, sex, friends, aaronic_priesthood, melchizedek_priesthood, calling, \
    ministering_brothers_sisters, ministering_assignment, temple_recommend, patriarchal_blessing, \
    living_ordinance, details, photo_url, kind, baptism_goal_date
    """

    public func stakes() async throws -> [Stake] {
        let rows: [Stake] = try await client
            .from("stakes")
            .select("id, name, unit_number, last_synced_at, missionaries")
            .execute()
            .value
        // Freshest stake first, so an unset default lands on the most recent scrape (matches the
        // Flutter sort on `last_synced_at` desc).
        return rows.sorted { ($0.lastSyncedAt ?? "") > ($1.lastSyncedAt ?? "") }
    }

    public func members(stakeID: String) async throws -> [Member] {
        // Scope to the selected stake — never return the RLS union of every stake the viewer can see
        // (that once merged two stakes into one list). RLS is still the gate underneath.
        let rows: [Member] = try await client
            .from("members")
            .select(Self.memberColumns)
            .eq("stake_id", value: stakeID)
            .order("unit_name")
            .order("name")
            .execute()
            .value
        return rows
    }
}
