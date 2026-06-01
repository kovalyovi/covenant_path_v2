import Foundation

/// A `units` row (id + name), for the Invite-power-user scope picker. Mirrors invite_page `_units`.
public struct UnitRow: Codable, Identifiable, Hashable, Sendable {
    public let id: String
    public let name: String?
    public init(id: String, name: String? = nil) { self.id = id; self.name = name }
    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        // id may be uuid (string) or numeric in odd rows.
        if let s = try? c.decode(String.self, forKey: .id) { id = s }
        else if let i = try? c.decode(Int.self, forKey: .id) { id = String(i) }
        else { id = UUID().uuidString }
        name = try c.decodeIfPresent(String.self, forKey: .name)
    }
    enum CodingKeys: String, CodingKey { case id, name }
}

/// An `invitations` row (power-user grants), for the Invite page list. Mirrors invite_page `_load`.
public struct Invitation: Codable, Identifiable, Hashable, Sendable {
    public let invitedEmail: String?
    public let role: String?
    public let unitID: String?
    public let status: String?
    public let invitedByEmail: String?
    public let createdAt: String?

    public enum CodingKeys: String, CodingKey {
        case invitedEmail = "invited_email"
        case role
        case unitID = "unit_id"
        case status
        case invitedByEmail = "invited_by_email"
        case createdAt = "created_at"
    }
    public var id: String { "\(invitedEmail ?? "")|\(unitID ?? "")|\(createdAt ?? "")" }
    public var isRevoked: Bool { status == "revoked" }
}

/// An `app_admins` row (admin console → Admins panel). Mirrors admin_page `_adminsF`.
public struct AppAdmin: Codable, Identifiable, Hashable, Sendable {
    public let email: String
    public let invitedByEmail: String?
    public enum CodingKeys: String, CodingKey {
        case email
        case invitedByEmail = "invited_by_email"
    }
    public var id: String { email }
}
