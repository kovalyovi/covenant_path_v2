import Foundation

/// A leader note on a member (the `member_comments` table, RLS-scoped). Read fields only; inserts
/// use `NewComment`. Mirrors the columns selected in `person_detail_page._CommentsSection`.
public struct MemberComment: Codable, Identifiable, Hashable, Sendable {
    public let authorEmail: String?
    public let authorName: String?
    public let body: String?
    public let createdAt: String?

    public enum CodingKeys: String, CodingKey {
        case authorEmail = "author_email"
        case authorName = "author_name"
        case body
        case createdAt = "created_at"
    }

    public init(authorEmail: String? = nil, authorName: String? = nil,
                body: String? = nil, createdAt: String? = nil) {
        self.authorEmail = authorEmail; self.authorName = authorName
        self.body = body; self.createdAt = createdAt
    }

    /// Stable id from author+timestamp (the table has no surfaced primary key in the select).
    public var id: String { "\(authorEmail ?? "")|\(createdAt ?? "")|\((body ?? "").prefix(12))" }

    /// "Who" line: prefer the recorded name, else the email.
    public var who: String { (authorName?.isEmpty == false ? authorName : authorEmail) ?? "" }
}

/// Insert payload for a new note (snake_case columns == DB). `unit_id`/`stake_id` may be nil.
/// Public because it appears in the public `SupabaseGateway.addComment` requirement.
public struct NewComment: Encodable {
    let stake_id: String?
    let unit_id: String?
    let member_person_uuid: String
    let author_email: String
    let body: String

    public init(stake_id: String?, unit_id: String?, member_person_uuid: String,
                author_email: String, body: String) {
        self.stake_id = stake_id; self.unit_id = unit_id
        self.member_person_uuid = member_person_uuid
        self.author_email = author_email; self.body = body
    }
}
