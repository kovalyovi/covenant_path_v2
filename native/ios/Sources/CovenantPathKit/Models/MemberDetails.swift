import Foundation

/// The rich `details` jsonb subtree used by the Person Detail page. Every field is optional and the
/// decoders are tolerant — a row synced before a schema bump, or a partial scrape, must still render
/// (mirrors the Flutter app's `d?['x']` null-guards everywhere). Shapes match `person_detail_page.dart`.
public struct MemberDetails: Codable, Hashable, Sendable {
    public var memberSince: String?
    public var firstLesson: String?
    public var sacramentMissed: Int?

    public var friends: [Friend]?
    public var ministeringBrothers: [String]?   // names (also tolerant of [{name}] — see decoder)
    public var ministeringSisters: [String]?
    public var sacrament: [SacramentEntry]?
    public var lessons: [Lesson]?
    public var callings: [String]?
    public var priesthoodOrdinations: [String]?
    public var ministeringAssignments: [String]?
    public var templeOrdinances: [String]?
    public var templeExperiences: [Toggle]?
    public var selfReliance: [Toggle]?
    public var tags: [String]?

    public enum CodingKeys: String, CodingKey {
        case memberSince, firstLesson, sacramentMissed
        case friends, ministeringBrothers, ministeringSisters, sacrament, lessons, callings
        case priesthoodOrdinations, ministeringAssignments, templeOrdinances, templeExperiences
        case selfReliance, tags
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        memberSince = try c.decodeStringLoose(.memberSince)
        firstLesson = try c.decodeStringLoose(.firstLesson)
        sacramentMissed = try c.decodeIntLoose(.sacramentMissed)
        friends = try c.decodeIfPresent([Friend].self, forKey: .friends)
        ministeringBrothers = try c.decodeNameList(.ministeringBrothers)
        ministeringSisters = try c.decodeNameList(.ministeringSisters)
        sacrament = try c.decodeIfPresent([SacramentEntry].self, forKey: .sacrament)
        lessons = try c.decodeIfPresent([Lesson].self, forKey: .lessons)
        callings = try c.decodeStringList(.callings)
        priesthoodOrdinations = try c.decodeStringList(.priesthoodOrdinations)
        ministeringAssignments = try c.decodeStringList(.ministeringAssignments)
        templeOrdinances = try c.decodeStringList(.templeOrdinances)
        templeExperiences = try c.decodeIfPresent([Toggle].self, forKey: .templeExperiences)
        selfReliance = try c.decodeIfPresent([Toggle].self, forKey: .selfReliance)
        tags = try c.decodeStringList(.tags)
    }

    public init() {}

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encodeIfPresent(memberSince, forKey: .memberSince)
        try c.encodeIfPresent(firstLesson, forKey: .firstLesson)
        try c.encodeIfPresent(sacramentMissed, forKey: .sacramentMissed)
        try c.encodeIfPresent(friends, forKey: .friends)
        try c.encodeIfPresent(ministeringBrothers, forKey: .ministeringBrothers)
        try c.encodeIfPresent(ministeringSisters, forKey: .ministeringSisters)
        try c.encodeIfPresent(sacrament, forKey: .sacrament)
        try c.encodeIfPresent(lessons, forKey: .lessons)
        try c.encodeIfPresent(callings, forKey: .callings)
        try c.encodeIfPresent(priesthoodOrdinations, forKey: .priesthoodOrdinations)
        try c.encodeIfPresent(ministeringAssignments, forKey: .ministeringAssignments)
        try c.encodeIfPresent(templeOrdinances, forKey: .templeOrdinances)
        try c.encodeIfPresent(templeExperiences, forKey: .templeExperiences)
        try c.encodeIfPresent(selfReliance, forKey: .selfReliance)
        try c.encodeIfPresent(tags, forKey: .tags)
    }

    // MARK: - nested shapes

    public struct Friend: Codable, Hashable, Sendable {
        public var name: String?
        public var unit: String?
        public var inStake: Bool?
        public init(name: String? = nil, unit: String? = nil, inStake: Bool? = nil) {
            self.name = name; self.unit = unit; self.inStake = inStake
        }
    }

    /// One Sunday in the sacrament-attendance timeline (stored newest-first).
    public struct SacramentEntry: Codable, Hashable, Sendable {
        public var label: String?
        public var attended: Bool?
        public var date: String?
        public init(label: String? = nil, attended: Bool? = nil, date: String? = nil) {
            self.label = label; self.attended = attended; self.date = date
        }
    }

    public struct Lesson: Codable, Hashable, Sendable {
        public var name: String?
        public var principles: [Principle]?
        public init(name: String? = nil, principles: [Principle]? = nil) {
            self.name = name; self.principles = principles
        }
    }

    public struct Principle: Codable, Hashable, Sendable {
        public var name: String?
        public var memberPresent: Bool?
        /// `taughtLevel` is "taught" when non-empty and not "0"/"0.0" (matches `_taught`). It may
        /// arrive as a number or string in the JSON, so we normalize to String.
        public var taughtLevel: String?

        public var isTaught: Bool {
            guard let s = taughtLevel, !s.isEmpty else { return false }
            return s != "0" && s != "0.0"
        }

        public enum CodingKeys: String, CodingKey { case name, memberPresent, taughtLevel }

        public init(name: String? = nil, memberPresent: Bool? = nil, taughtLevel: String? = nil) {
            self.name = name; self.memberPresent = memberPresent; self.taughtLevel = taughtLevel
        }

        public init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            name = try c.decodeStringLoose(.name)
            memberPresent = try c.decodeIfPresent(Bool.self, forKey: .memberPresent)
            taughtLevel = try c.decodeStringLoose(.taughtLevel)
        }
    }

    /// A `{name, done}` toggle (temple experiences, self-reliance classes).
    public struct Toggle: Codable, Hashable, Sendable {
        public var name: String?
        public var done: Bool?
        public init(name: String? = nil, done: Bool? = nil) {
            self.name = name; self.done = done
        }
        public init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            name = try c.decodeStringLoose(.name)
            done = try c.decodeIfPresent(Bool.self, forKey: .done)
        }
        public enum CodingKeys: String, CodingKey { case name, done }
    }
}

// MARK: - tolerant decode helpers

extension KeyedDecodingContainer {
    /// Decode a value that may be a String, number, or bool into a String? (so `taughtLevel: 1`
    /// and `taughtLevel: "1"` both work, like Dart's `.toString()`).
    func decodeStringLoose(_ key: Key) throws -> String? {
        if let s = try? decodeIfPresent(String.self, forKey: key) { return s }
        if let d = try? decodeIfPresent(Double.self, forKey: key) {
            // Render integral doubles without a trailing ".0" to match Dart int.toString().
            if d == d.rounded() { return String(Int(d)) }
            return String(d)
        }
        if let i = try? decodeIfPresent(Int.self, forKey: key) { return String(i) }
        if let b = try? decodeIfPresent(Bool.self, forKey: key) { return b ? "true" : "false" }
        return nil
    }

    func decodeIntLoose(_ key: Key) throws -> Int? {
        if let i = try? decodeIfPresent(Int.self, forKey: key) { return i }
        if let s = try? decodeIfPresent(String.self, forKey: key) { return Int(s) }
        if let d = try? decodeIfPresent(Double.self, forKey: key) { return Int(d) }
        return nil
    }

    /// A list of plain strings, dropping nulls/empties (matches Flutter's `_strings`).
    func decodeStringList(_ key: Key) throws -> [String]? {
        guard let arr = try? decodeIfPresent([String?].self, forKey: key) else { return nil }
        return arr.compactMap { $0 }.filter { !$0.isEmpty }
    }

    /// Names that may be stored either as `["A", "B"]` or `[{"name":"A"}, …]` — the spec shows the
    /// object form for ministeringBrothers/Sisters, but flat strings appear in some rows. Accept both.
    func decodeNameList(_ key: Key) throws -> [String]? {
        if let arr = try? decodeIfPresent([String].self, forKey: key) {
            return arr.filter { !$0.isEmpty }
        }
        if let objs = try? decodeIfPresent([MemberDetails.Friend].self, forKey: key) {
            return objs.compactMap { $0.name }.filter { !$0.isEmpty }
        }
        return nil
    }
}
