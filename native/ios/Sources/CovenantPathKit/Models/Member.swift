import Foundation

/// One tracked person (a `members` row). The flat status fields are free-text on the backend:
/// `"Yes"` / `"No"` / `"N/A"` or a sentinel like `"needs-profile-api"` / `"blocked: …"`. We keep
/// them as `String?` and interpret them in `Milestones` exactly as the Flutter app does
/// (`m['friends'] == 'Yes'`), so the business logic stays a faithful port.
///
/// `CodingKeys` map snake_case DB columns → camelCase Swift, matching the dashboard select string
/// in the spec / `dashboard_page.dart` `_columns`.
public struct Member: Codable, Identifiable, Hashable, Sendable {
    public let personUUID: String?
    public let stakeID: String?
    public let unitID: String?
    public let name: String?
    public let unitName: String?
    public let baptismDate: String?
    public let baptismGoalDate: String?
    public let birthDate: String?
    public let membershipDuration: String?
    public let sex: String?

    // Yes/No/N-A status fields.
    public let friends: String?
    public let friendsCount: Int?
    public let aaronicPriesthood: String?
    public let melchizedekPriesthood: String?
    public let calling: String?
    public let ministeringBrothersSisters: String?
    public let ministeringAssignment: String?
    public let templeRecommend: String?
    public let patriarchalBlessing: String?
    public let livingOrdinance: String?

    public let kind: String?        // "new_member" | "investigator" | "returning"
    public let photoURL: String?
    public let details: MemberDetails?

    /// Stable identity. `person_uuid` is the real key; fall back to name, then a stable composite, so
    /// SwiftUI lists never collide on a nil id (mirrors Flutter's `person_uuid ?? name` keying). The
    /// fallback is deterministic (no random UUID) so a row keeps the same id across re-renders.
    public var id: String {
        personUUID ?? name ?? "\(unitName ?? "")|\(baptismDate ?? "")|\(birthDate ?? "")"
    }

    public enum CodingKeys: String, CodingKey {
        case personUUID = "person_uuid"
        case stakeID = "stake_id"
        case unitID = "unit_id"
        case name
        case unitName = "unit_name"
        case baptismDate = "baptism_date"
        case baptismGoalDate = "baptism_goal_date"
        case birthDate = "birth_date"
        case membershipDuration = "membership_duration"
        case sex
        case friends
        case friendsCount = "friends_count"
        case aaronicPriesthood = "aaronic_priesthood"
        case melchizedekPriesthood = "melchizedek_priesthood"
        case calling
        case ministeringBrothersSisters = "ministering_brothers_sisters"
        case ministeringAssignment = "ministering_assignment"
        case templeRecommend = "temple_recommend"
        case patriarchalBlessing = "patriarchal_blessing"
        case livingOrdinance = "living_ordinance"
        case kind
        case photoURL = "photo_url"
        case details
    }

    public init(
        personUUID: String? = nil, stakeID: String? = nil, unitID: String? = nil,
        name: String? = nil, unitName: String? = nil, baptismDate: String? = nil,
        baptismGoalDate: String? = nil, birthDate: String? = nil, membershipDuration: String? = nil,
        sex: String? = nil, friends: String? = nil, friendsCount: Int? = nil, aaronicPriesthood: String? = nil,
        melchizedekPriesthood: String? = nil, calling: String? = nil,
        ministeringBrothersSisters: String? = nil, ministeringAssignment: String? = nil,
        templeRecommend: String? = nil, patriarchalBlessing: String? = nil,
        livingOrdinance: String? = nil, kind: String? = nil, photoURL: String? = nil,
        details: MemberDetails? = nil
    ) {
        self.personUUID = personUUID; self.stakeID = stakeID; self.unitID = unitID
        self.name = name; self.unitName = unitName; self.baptismDate = baptismDate
        self.baptismGoalDate = baptismGoalDate; self.birthDate = birthDate
        self.membershipDuration = membershipDuration; self.sex = sex; self.friends = friends
        self.friendsCount = friendsCount
        self.aaronicPriesthood = aaronicPriesthood; self.melchizedekPriesthood = melchizedekPriesthood
        self.calling = calling; self.ministeringBrothersSisters = ministeringBrothersSisters
        self.ministeringAssignment = ministeringAssignment; self.templeRecommend = templeRecommend
        self.patriarchalBlessing = patriarchalBlessing; self.livingOrdinance = livingOrdinance
        self.kind = kind; self.photoURL = photoURL; self.details = details
    }

    // MARK: - derived convenience (read-only; pure)

    public var isInvestigator: Bool { kind == "investigator" }
    public var isMale: Bool { sex == "M" }
    public var displayName: String { (name?.isEmpty == false) ? name! : "—" }

    /// "Yes" exactly (sentinels and "No"/"N/A" are NOT yes) — the single predicate the milestone
    /// completion checks use, kept here so the rule lives in one place.
    public func isYes(_ value: String?) -> Bool { value == "Yes" }
}
