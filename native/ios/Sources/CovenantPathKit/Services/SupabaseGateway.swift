import Foundation
import Supabase

/// Misc read-only + RPC Supabase access that doesn't belong to the dashboard member load: admin
/// check, member notes (read/insert), power-user invites, and the admin console's Supabase-side
/// data (units, invitations, app_admins, revoke RPCs). RLS gates everything (the golden rule).
public protocol SupabaseGateway: Sendable {
    func isAdmin() async -> Bool

    func comments(memberUUID: String) async throws -> [MemberComment]
    func addComment(_ comment: NewComment) async throws
    /// One bulk fetch of a stake's notes for the list-row note lines (RLS-scoped like members).
    func noteRows(stakeID: String) async throws -> [MemberNoteRow]

    func units() async throws -> [UnitRow]
    func invitations() async throws -> [Invitation]
    /// Returns the number of scopes cloned (the rpc returns an int).
    @discardableResult func invitePowerUser(email: String, unitID: String?) async throws -> Int
    func revokePowerUser(email: String) async throws

    func appAdmins() async throws -> [AppAdmin]
    func revokeAdmin(email: String) async throws

    /// #5b: a stake leader opts their stake in/out of Google-Sheet generation (RPC enforces the role).
    func setStakeSheetsEnabled(stakeID: String, enabled: Bool) async throws
}

public struct SupabaseGatewayImpl: SupabaseGateway {
    private let client: SupabaseClient
    public init(client: SupabaseClient) { self.client = client }

    public func isAdmin() async -> Bool {
        do {
            let v: Bool = try await client.rpc("is_admin").execute().value
            return v
        } catch {
            return false
        }
    }

    // MARK: - member notes

    public func comments(memberUUID: String) async throws -> [MemberComment] {
        guard !memberUUID.isEmpty else { return [] }
        let rows: [MemberComment] = try await client
            .from("member_comments")
            .select("author_email, author_name, body, created_at")
            .eq("member_person_uuid", value: memberUUID)
            .order("created_at")
            .execute()
            .value
        return rows
    }

    public func addComment(_ comment: NewComment) async throws {
        try await client.from("member_comments").insert(comment).execute()
    }

    public func noteRows(stakeID: String) async throws -> [MemberNoteRow] {
        guard !stakeID.isEmpty else { return [] }
        let rows: [MemberNoteRow] = try await client
            .from("member_comments")
            .select("member_person_uuid, body, created_at")
            .eq("stake_id", value: stakeID)
            .execute()
            .value
        return rows
    }

    // MARK: - invites

    public func units() async throws -> [UnitRow] {
        let rows: [UnitRow] = try await client
            .from("units").select("id, name").order("name").execute().value
        return rows
    }

    public func invitations() async throws -> [Invitation] {
        let rows: [Invitation] = try await client
            .from("invitations")
            .select("invited_email, role, unit_id, status, invited_by_email, created_at")
            .order("created_at", ascending: false)
            .execute()
            .value
        return rows
    }

    @discardableResult
    public func invitePowerUser(email: String, unitID: String?) async throws -> Int {
        // The rpc returns the number of scopes cloned. Params mirror the Dart `p_email`/`p_unit`.
        let n: Int
        if let unitID, !unitID.isEmpty {
            n = try await client.rpc("invite_power_user",
                                     params: InviteParams(p_email: email, p_unit: unitID))
                .execute().value
        } else {
            n = try await client.rpc("invite_power_user",
                                     params: InviteEmailParam(p_email: email))
                .execute().value
        }
        return n
    }

    public func revokePowerUser(email: String) async throws {
        try await client.rpc("revoke_power_user", params: EmailParam(p_email: email)).execute()
    }

    // MARK: - admin console

    public func appAdmins() async throws -> [AppAdmin] {
        let rows: [AppAdmin] = try await client
            .from("app_admins").select("email, invited_by_email").execute().value
        return rows
    }

    public func revokeAdmin(email: String) async throws {
        try await client.rpc("revoke_admin", params: EmailParam(p_email: email)).execute()
    }

    /// #5b: a stake leader toggles Google-Sheet generation for their stake (the RPC enforces the role).
    public func setStakeSheetsEnabled(stakeID: String, enabled: Bool) async throws {
        try await client.rpc("set_stake_sheets_enabled",
                             params: SheetsToggleParam(p_stake_id: stakeID, p_enabled: enabled)).execute()
    }
}

private struct SheetsToggleParam: Encodable { let p_stake_id: String; let p_enabled: Bool }

// MARK: - RPC param payloads (Encodable so supabase-swift can serialize them)

private struct EmailParam: Encodable { let p_email: String }
private struct InviteEmailParam: Encodable { let p_email: String }
private struct InviteParams: Encodable { let p_email: String; let p_unit: String }
