import Foundation

/// Latest-note index for list rows — built from ONE bulk member_comments query per stake load
/// (RLS scopes the rows server-side with the same policy as members). Pure logic, mirrored from
/// the web's `logic/notes.ts` (`buildNotesIndex`) and Kotlin's `logic/NotesIndex.kt`.

/// One member_comments row, as the bulk list query selects it.
public struct MemberNoteRow: Decodable, Sendable {
    public let memberPersonUUID: String?
    public let body: String?
    public let createdAt: String?

    public init(memberPersonUUID: String?, body: String?, createdAt: String?) {
        self.memberPersonUUID = memberPersonUUID
        self.body = body
        self.createdAt = createdAt
    }

    enum CodingKeys: String, CodingKey {
        case memberPersonUUID = "member_person_uuid"
        case body
        case createdAt = "created_at"
    }
}

/// The newest leader note on a member + how many there are in total.
public struct NoteSummary: Equatable, Sendable {
    public let count: Int
    public let latest: String
    public let latestAt: String
}

public enum NotesIndex {
    /// person_uuid -> newest note + count. Rows without a uuid or with a blank body are skipped.
    public static func build(_ rows: [MemberNoteRow]) -> [String: NoteSummary] {
        var out: [String: NoteSummary] = [:]
        for r in rows {
            guard let uuid = r.memberPersonUUID, !uuid.isEmpty else { continue }
            let body = (r.body ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            guard !body.isEmpty else { continue }
            let at = r.createdAt ?? ""
            if let cur = out[uuid] {
                // ISO timestamps from one column share a format, so string compare orders correctly.
                if at >= cur.latestAt {
                    out[uuid] = NoteSummary(count: cur.count + 1, latest: body, latestAt: at)
                } else {
                    out[uuid] = NoteSummary(count: cur.count + 1, latest: cur.latest, latestAt: cur.latestAt)
                }
            } else {
                out[uuid] = NoteSummary(count: 1, latest: body, latestAt: at)
            }
        }
        return out
    }
}
