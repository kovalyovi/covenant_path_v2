import Foundation

/// Leadership / staffing gap rule (#12). Given a unit's roster of held callings (from the Member Tools
/// bulk payload, stored on `units.staffing`), determine which REQUIRED positions are filled and which
/// are gaps — "is there a ward mission leader? at least 2 ward missionaries? an EQ president? an RS
/// president?". Pure → a 1:1 mirror of the web `apps/web/src/logic/staffing.ts`. The position strings
/// are the LCR calling names.

/// One held calling on a unit's roster.
public struct StaffingMember: Codable, Hashable, Sendable {
    public var position: String
    public var person: String?
    public var personUuid: String?
    public var setApart: Bool?
    public init(position: String, person: String? = nil, personUuid: String? = nil, setApart: Bool? = nil) {
        self.position = position; self.person = person; self.personUuid = personUuid; self.setApart = setApart
    }

    enum CodingKeys: String, CodingKey {
        case position, person
        case personUuid = "person_uuid"
        case setApart = "set_apart"
    }
}

/// Per-required-role fill status for a unit — `ok` when at least `min` are serving.
public struct RoleStatus: Hashable, Sendable {
    public let key: String
    public let label: String
    public let have: Int
    public let min: Int
    public let ok: Bool
    public let holders: [String] // names serving in this role (may be empty when unknown)
    public init(key: String, label: String, have: Int, min: Int, ok: Bool, holders: [String]) {
        self.key = key; self.label = label; self.have = have; self.min = min; self.ok = ok; self.holders = holders
    }
}

public enum Staffing {

    struct RequiredRole {
        let key: String
        let label: String
        let min: Int
        let match: (String) -> Bool
    }

    /// The roster every unit is expected to have for new-member success to be trackable (#12). This is
    /// the single definition the gap check + the UI read — extend here as leaders ask for more.
    static let requiredRoles: [RequiredRole] = [
        RequiredRole(key: "wml", label: "Ward mission leader", min: 1) {
            staffingMatches($0, #"(ward|branch) mission leader"#) && !staffingMatches($0, #"assistant|asst"#)
        },
        RequiredRole(key: "ward_missionaries", label: "Ward missionaries", min: 2) {
            staffingMatches($0, #"(ward|branch) missionary"#)
        },
        RequiredRole(key: "eq_pres", label: "Elders Quorum president", min: 1) {
            staffingMatches($0, #"elders quorum president"#) && !staffingMatches($0, #"counselor|assistant|secretary|clerk"#)
        },
        RequiredRole(key: "rs_pres", label: "Relief Society president", min: 1) {
            staffingMatches($0, #"relief society president"#) && !staffingMatches($0, #"counselor|assistant|secretary|clerk"#)
        },
    ]

    /// Per-required-role fill status for a unit's roster — `ok` when at least `min` are serving.
    public static func gaps(_ roster: [StaffingMember]) -> [RoleStatus] {
        requiredRoles.map { role in
            let held = roster.filter { role.match($0.position) }
            let holders = held.compactMap { m -> String? in
                guard let n = m.person, !n.trimmingCharacters(in: .whitespaces).isEmpty else { return nil }
                return n
            }
            return RoleStatus(key: role.key, label: role.label, have: held.count, min: role.min,
                              ok: held.count >= role.min, holders: holders)
        }
    }

    /// Count of unmet required roles for a unit (0 = fully staffed for the tracked positions).
    public static func gapCount(_ roster: [StaffingMember]) -> Int {
        gaps(roster).filter { !$0.ok }.count
    }
}

/// Case-insensitive regex `test` (mirrors the web `/…/i.test(p)` checks). File-scope so the
/// `requiredRoles` closures reference it without static-context qualification.
private func staffingMatches(_ s: String, _ pattern: String) -> Bool {
    s.range(of: pattern, options: [.regularExpression, .caseInsensitive]) != nil
}
