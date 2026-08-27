import Foundation

/// "Golden Hour" = a new member's first-year integration milestones. This is a faithful port of
/// `apps/viewer/lib/golden_hour.dart` — the SINGLE source of milestone definitions in the Flutter
/// app — translated to pure Swift so it's unit-testable without UI. Colors/icons are expressed as
/// platform-neutral identities (`MilestoneStyle`) and mapped to SwiftUI in the view layer.
///
/// Each milestone is gated to who it can apply to (`eligible`); completion stats are eligible-only
/// so ineligible people (wrong age/sex/tenure) never drag a number down.

public struct Milestone: Identifiable, Sendable {
    public let label: String          // full name (detail + accessibility)
    public let abbr: String           // chip label (1–2 chars)
    public let style: MilestoneStyle  // category identity color + icon
    public let complete: @Sendable (Member) -> Bool
    public let eligible: @Sendable (Member) -> Bool
    /// The member field this milestone reads (mirrors web `Milestone.field`) — so an N/A value can be
    /// detected and EXCLUDED from "missing/incomplete" lists, and the raw sentinel/empty value can be
    /// recognized as a DATA ISSUE in the completion rows. Read via the keyed accessor below; a
    /// milestone derived purely from logic (none today) can leave it nil.
    public let field: String?

    public var id: String { label }

    public init(_ label: String, _ abbr: String, style: MilestoneStyle,
                field: String? = nil,
                eligible: @escaping @Sendable (Member) -> Bool = { _ in true },
                complete: @escaping @Sendable (Member) -> Bool) {
        self.label = label; self.abbr = abbr; self.style = style; self.field = field
        self.eligible = eligible; self.complete = complete
    }
}

/// Platform-neutral style identity for a milestone — an RGB hex (matching the Flutter `Color`
/// constants) and an SF-Symbol-ish category name resolved in the view layer.
public struct MilestoneStyle: Sendable {
    public let hex: UInt32       // 0xRRGGBB, identical to golden_hour.dart's Color(0x..)
    public let symbol: String    // SF Symbol name (chosen to echo the Material icon's meaning)
    public init(hex: UInt32, symbol: String) { self.hex = hex; self.symbol = symbol }
}

public enum Milestones {

    /// Compiled once (was recompiled on every `memberOneYearPlus` call, which runs per member in
    /// eligibility scans + list sorts).
    private static let yearsRegex = try? NSRegularExpression(pattern: #"(\d+)\s*year"#)

    /// The ordered milestone list — same order, same labels/abbrs, same predicates as Flutter.
    /// Baptism is intentionally NOT a milestone (see golden_hour.dart).
    public static let all: [Milestone] = [
        Milestone("Friends", "F",
                  style: .init(hex: 0xD81B60, symbol: "hand.raised.fill"),         // pink · everyone
                  field: "friends",
                  complete: { $0.friends == "Yes" }),
        Milestone("Calling", "C",
                  style: .init(hex: 0x6A1B9A, symbol: "person.text.rectangle"),    // purple
                  field: "calling",
                  eligible: { turnsAtLeast($0, 12) },
                  complete: { $0.calling == "Yes" }),
        Milestone("Has ministers", "M",
                  style: .init(hex: 0x00838F, symbol: "person.2.wave.2"),          // cyan · everyone
                  field: "ministering_brothers_sisters",
                  complete: { $0.ministeringBrothersSisters == "Yes" }),
        Milestone("Ministering assignment", "MA",
                  style: .init(hex: 0xEF6C00, symbol: "hands.sparkles"),           // orange · 14+
                  field: "ministering_assignment",
                  eligible: { turnsAtLeast($0, 14) },
                  complete: { $0.ministeringAssignment == "Yes" }),
        Milestone("Aaronic Priesthood", "AP",
                  style: .init(hex: 0x1565C0, symbol: "medal"),                    // blue
                  field: "aaronic_priesthood",
                  eligible: { $0.isMale && turnsAtLeast($0, 12) },
                  complete: { $0.aaronicPriesthood == "Yes" }),
        Milestone("Melchizedek Priesthood", "MP",
                  style: .init(hex: 0x2E7D32, symbol: "rosette"),                  // green
                  field: "melchizedek_priesthood",
                  eligible: { melchizedekEligible($0) },
                  complete: { $0.melchizedekPriesthood == "Yes" }),
        // Temple Ordinances and Experiences: genealogy + proxy baptisms, both from the year someone
        // turns 12 (limited-use recommend age — same by-year rule as calling/Aaronic).
        Milestone("Family name prepared", "FN",
                  style: .init(hex: 0x6D4C41, symbol: "book.closed"),              // brown · 12+
                  field: "family_name_prepared",
                  eligible: { turnsAtLeast($0, 12) },
                  complete: { familyNameValue($0) == "Yes" }),
        Milestone("First temple visit", "FT",
                  style: .init(hex: 0x00897B, symbol: "building.columns"),         // teal · 12+
                  field: "first_temple_visit",
                  eligible: { turnsAtLeast($0, 12) },
                  complete: { firstTempleVisitValue($0) == "Yes" }),
    ]

    /// Milestones that apply to this member (the eligible subset), in canonical order.
    public static func applicable(to m: Member) -> [Milestone] {
        all.filter { $0.eligible(m) }
    }

    // MARK: - eligibility predicates (ports of golden_hour.dart privates)

    /// "Turns at least `age` by the end of this calendar year" — the Church by-year rule (an
    /// 11-year-old turning 12 this year counts). Unknown birth → not eligible for age-gated ones.
    public static func turnsAtLeast(_ m: Member, _ age: Int) -> Bool {
        guard let by = MemberDate.yearOf(m.birthDate) else { return false }
        let year = MemberDate.cal.component(.year, from: Date())
        return (year - by) >= age
    }

    /// Member ≥ 1 year: baptized ≥ 365 days ago, OR `membership_duration` mentions "N year(s)" with N≥1.
    public static func memberOneYearPlus(_ m: Member) -> Bool {
        if let b = MemberDate.parse(m.baptismDate) {
            let days = MemberDate.cal.dateComponents([.day], from: b, to: Date()).day ?? 0
            return days >= 365
        }
        // `(\d+)\s*year` on the lowercased membership_duration (regex compiled once, not per call).
        let s = (m.membershipDuration ?? "").lowercased()
        if let re = yearsRegex,
           let match = re.firstMatch(in: s, range: NSRange(s.startIndex..<s.endIndex, in: s)),
           let r = Range(match.range(at: 1), in: s), let n = Int(s[r]) {
            return n >= 1
        }
        return false
    }

    /// Actual current age from a full birth date when present, else by-year (`now.year - birthYear`).
    /// `nil` when birth is unknown. Mirrors `_ageNow`.
    public static func ageNow(_ m: Member) -> Int? {
        if let d = MemberDate.parse(m.birthDate) {
            let comps = MemberDate.cal.dateComponents([.year], from: d, to: Date())
            return comps.year
        }
        guard let by = MemberDate.yearOf(m.birthDate) else { return nil }
        return MemberDate.cal.component(.year, from: Date()) - by
    }

    public static func ageNowAtLeast(_ m: Member, _ age: Int) -> Bool {
        guard let a = ageNow(m) else { return false }
        return a >= age
    }

    /// Display age (e.g. "35 yrs"), or nil when unknown/negative — matches `ageOf`.
    public static func ageLabel(_ m: Member) -> String? {
        guard let a = ageNow(m), a >= 0 else { return nil }
        return "\(a) yrs"
    }

    // MARK: - completion math (eligible-only), used by Golden Hour summary

    /// (done, eligible) counts for a milestone across `rows`.
    public static func completion(_ ms: Milestone, in rows: [Member]) -> (done: Int, eligible: Int) {
        let eligible = rows.filter(ms.eligible)
        let done = eligible.filter(ms.complete)
        return (done.count, eligible.count)
    }

    /// Eligible members in `rows` still missing this milestone (the "still need" drill list).
    public static func missing(_ ms: Milestone, in rows: [Member]) -> [Member] {
        rows.filter { ms.eligible($0) && !ms.complete($0) }
    }

    /// Average per-member completion fraction across `rows` (eligible-only per member). Mirrors
    /// `_avgCompletion`; used for any "overall %" stat.
    public static func averageCompletion(_ rows: [Member]) -> Double {
        guard !rows.isEmpty else { return 0 }
        var sum = 0.0
        for m in rows {
            let applic = applicable(to: m)
            guard !applic.isEmpty else { continue }
            let done = applic.filter { $0.complete(m) }.count
            sum += Double(done) / Double(applic.count)
        }
        return sum / Double(rows.count)
    }

    /// Index of the first not-yet-complete applicable milestone (the suggested "next step"), or nil.
    public static func nextStepIndex(for m: Member) -> Int? {
        let list = applicable(to: m)
        return list.firstIndex { !$0.complete(m) }
    }

    /// Per-unit Golden Hour rollup for the #8d indicators: the share of PEOPLE fully complete (a
    /// SECTIONED ring — one arc/person) and the share of ITEMS complete overall (a FILLED ring).
    /// Eligible-only per member (N/A excluded); a member with no applicable milestones counts as fully
    /// complete (nothing outstanding). Ranked by people desc. Mirrors the web `unitGoldenHour`.
    public struct UnitGoldenHour: Sendable {
        public let unit: String
        public let people: Int        // members in the unit
        public let fullyComplete: Int // members with EVERY applicable milestone complete
        public let itemsDone: Int     // total complete applicable milestones across the unit
        public let itemsTotal: Int    // total applicable milestones across the unit
        public init(unit: String, people: Int, fullyComplete: Int, itemsDone: Int, itemsTotal: Int) {
            self.unit = unit; self.people = people; self.fullyComplete = fullyComplete
            self.itemsDone = itemsDone; self.itemsTotal = itemsTotal
        }
    }

    public static func unitGoldenHour(_ rows: [Member]) -> [UnitGoldenHour] {
        var by: [String: [Member]] = [:]
        for m in rows { by[m.unitName ?? "—", default: []].append(m) }
        var out: [UnitGoldenHour] = []
        for (unit, members) in by {
            var fully = 0, done = 0, total = 0
            for m in members {
                let applic = applicable(to: m)
                let c = applic.filter { $0.complete(m) }.count
                done += c
                total += applic.count
                if applic.isEmpty || c == applic.count { fully += 1 }
            }
            out.append(UnitGoldenHour(unit: unit, people: members.count,
                                      fullyComplete: fully, itemsDone: done, itemsTotal: total))
        }
        out.sort { $0.people > $1.people }
        return out
    }

    // MARK: - per-field eligibility for the member-detail view (mirrors web milestones.ts so every
    // surface hides the same rows: no priesthood for women, no calling for a child, …).

    public static func callingEligible(_ m: Member) -> Bool { turnsAtLeast(m, 12) }
    public static func ministeringAssignmentEligible(_ m: Member) -> Bool { turnsAtLeast(m, 14) }
    public static func aaronicEligible(_ m: Member) -> Bool { m.isMale && turnsAtLeast(m, 12) }
    /// Melchizedek Priesthood applies to an adult man (18+) a member ~a year — OR to any man the
    /// records show is ALREADY ordained. The one-year mark is guidance, not a rule: a convert can be
    /// (and often is) ordained an elder sooner, e.g. before a mission or a temple sealing. Gating
    /// purely on duration made a genuinely-ordained brother read "N/A" instead of "Yes". So:
    /// ordained -> Yes always; not ordained and under a year -> N/A; over a year -> No (a real gap).
    public static func melchizedekEligible(_ m: Member) -> Bool {
        m.isMale && (m.melchizedekPriesthood == "Yes"
                     || (ageNowAtLeast(m, 18) && memberOneYearPlus(m)))
    }
    /// Priesthood section applies to males old enough for the Aaronic priesthood (12+).
    public static func priesthoodEligible(_ m: Member) -> Bool { m.isMale && turnsAtLeast(m, 12) }
    /// Temple recommend (incl. limited-use) and a patriarchal blessing both start around age 12.
    public static func templeRecommendEligible(_ m: Member) -> Bool { turnsAtLeast(m, 12) }
    public static func patriarchalEligible(_ m: Member) -> Bool { turnsAtLeast(m, 12) }

    /// Endowment eligibility: an adult (18+) who's been a member ~1 year (same gate as the report).
    public static func endowmentEligible(_ m: Member) -> Bool {
        ageNowAtLeast(m, 18) && memberOneYearPlus(m)
    }

    // MARK: - Temple Ordinances and Experiences (family name + first temple visit), mirrors
    // web milestones.ts `templeExperienceValue` / `templeExperienceDisplay`.

    /// Effective Yes/No for a temple-experience field. The flat column (filled by the daily sync)
    /// wins; a row not yet re-synced falls back to `details.templeExperiences` — the same LCR
    /// commitments, scraped earlier. Returns the raw flat value (sentinel/empty) when neither knows.
    public static func templeExperienceValue(_ m: Member, flat: String?, needle: String) -> String {
        let v = flat ?? ""
        if v == "Yes" || v == "No" || v == "N/A" { return v }
        for t in m.details?.templeExperiences ?? []
        where (t.name ?? "").lowercased().contains(needle) {
            return t.done == true ? "Yes" : "No"
        }
        return v
    }

    /// Genealogy: the "Prepare a Family Name for the Temple" commitment.
    public static func familyNameValue(_ m: Member) -> String {
        templeExperienceValue(m, flat: m.familyNamePrepared, needle: "family name")
    }

    /// First temple visit: the "Perform Baptisms for Deceased Ancestors" commitment.
    public static func firstTempleVisitValue(_ m: Member) -> String {
        templeExperienceValue(m, flat: m.firstTempleVisit, needle: "baptisms for deceased")
    }

    /// Family name + first temple visit start at the limited-use recommend age (12, by-year rule).
    public static func templeExperienceEligible(_ m: Member) -> Bool { turnsAtLeast(m, 12) }

    /// Display: same N/A-for-ineligible gate as endowment (an under-12 can't do proxy baptisms yet,
    /// so a raw "No" misleads); a real "Yes" is always kept.
    public static func familyNameDisplay(_ m: Member) -> String {
        let v = familyNameValue(m)
        if v == "Yes" { return "Yes" }
        return templeExperienceEligible(m) ? v : "N/A"
    }

    public static func firstTempleVisitDisplay(_ m: Member) -> String {
        let v = firstTempleVisitValue(m)
        if v == "Yes" { return "Yes" }
        return templeExperienceEligible(m) ? v : "N/A"
    }
    /// Endowment (living_ordinance) display: "N/A" for the not-yet-eligible (a raw "No" misleads —
    /// they can't be endowed yet); a real "Yes" is always kept.
    public static func endowmentDisplay(_ m: Member) -> String {
        let v = m.livingOrdinance ?? ""
        if v == "Yes" { return "Yes" }
        return endowmentEligible(m) ? v : "N/A"
    }

    /// Fraction 0..1 of this member's APPLICABLE milestones that are complete — drives the detail
    /// completion ring (full + green at 1.0). Friends + Has-ministers apply to everyone, so ≥1 applies.
    public static func completionOf(_ m: Member) -> Double {
        let applic = applicable(to: m)
        guard !applic.isEmpty else { return 0 }
        return Double(applic.filter { $0.complete(m) }.count) / Double(applic.count)
    }

    /// The Needs view tracks the 6 Golden Hour milestones PLUS the longer-horizon covenants we also
    /// record (temple recommend, endowment, patriarchal blessing) — so leaders see everyone eligible-
    /// but-missing each. `all` stays the integration-only completion basis; this is the superset.
    public static let needsCategories: [Milestone] = all + [
        Milestone("Temple Recommend", "TR", style: .init(hex: 0x5E35B1, symbol: "checkmark.seal"),
                  field: "temple_recommend",
                  eligible: { templeRecommendEligible($0) },
                  complete: { $0.templeRecommend == "Active" }),
        Milestone("Endowment", "EN", style: .init(hex: 0x00695C, symbol: "building.columns"),
                  field: "living_ordinance",
                  eligible: { endowmentEligible($0) },
                  complete: { $0.livingOrdinance == "Yes" }),
        Milestone("Patriarchal Blessing", "PB", style: .init(hex: 0xAD1457, symbol: "book.closed"),
                  field: "patriarchal_blessing",
                  eligible: { patriarchalEligible($0) },
                  complete: { $0.patriarchalBlessing == "Yes" }),
    ]

    // MARK: - raw field value by snake_case key (mirrors web `m[ms.field]`)

    /// The raw flat string value for a milestone's `field` (snake_case DB column key), or nil when the
    /// milestone has no single field. Used by `expected` / `goldenHourRows` to recognize N/A and the
    /// sentinel/empty data-issue case. Mirrors the web reading `m[ms.field]`.
    public static func rawValue(of field: String?, for m: Member) -> String? {
        guard let field else { return nil }
        switch field {
        case "friends": return m.friends
        case "calling": return m.calling
        case "ministering_brothers_sisters": return m.ministeringBrothersSisters
        case "ministering_assignment": return m.ministeringAssignment
        case "aaronic_priesthood": return m.aaronicPriesthood
        case "melchizedek_priesthood": return m.melchizedekPriesthood
        case "family_name_prepared": return m.familyNamePrepared
        case "first_temple_visit": return m.firstTempleVisit
        case "temple_recommend": return m.templeRecommend
        case "living_ordinance": return m.livingOrdinance
        case "patriarchal_blessing": return m.patriarchalBlessing
        default: return nil
        }
    }

    // MARK: - expected / goldenHourRows / nextSteps (mirror web milestones.ts)

    /// Whether a member is EXPECTED to complete this milestone: eligible AND the underlying field
    /// isn't N/A. The gate the "needs / missing / incomplete" surfaces use so an N/A field is excluded
    /// entirely (N/A ≠ not-done). Mirrors web `expected`. The temple-experience + endowment fields
    /// derive N/A client-side for ineligible-by-age people, so honor that derived value too.
    public static func expected(_ ms: Milestone, _ m: Member) -> Bool {
        guard ms.eligible(m) else { return false }
        if let f = ms.field {
            if FieldDisplayLogic.isNA(rawValue(of: f, for: m)) { return false }
            if f == "family_name_prepared" { return !FieldDisplayLogic.isNA(familyNameDisplay(m)) }
            if f == "first_temple_visit" { return !FieldDisplayLogic.isNA(firstTempleVisitDisplay(m)) }
            if f == "living_ordinance" { return !FieldDisplayLogic.isNA(endowmentDisplay(m)) }
        }
        return true
    }

    /// A member is "missing" a milestone when they're EXPECTED to have it but haven't completed it.
    /// The single helper every needs/incomplete/completion surface shares. Mirrors web `isMissing`.
    public static func isMissing(_ ms: Milestone, _ m: Member) -> Bool {
        expected(ms, m) && !ms.complete(m)
    }

    /// Status of one Golden Hour completion ROW (mirrors web `GhRowStatus`).
    public enum GhRowStatus: Sendable, Equatable { case done, notDone, issue }

    /// One Golden Hour completion row: a milestone + its status (mirrors web `GhRow`).
    public struct GhRow: Identifiable, Sendable {
        public let milestone: Milestone
        public let status: GhRowStatus
        public var id: String { milestone.abbr }
    }

    /// Whether a milestone's underlying field value is a DATA ISSUE for this member: the field is
    /// present on the milestone, it isn't complete, and the raw value is a sentinel OR null/empty.
    /// A genuine recorded "No"/"Expired"/etc. is an honest not-done, never a data issue. Milestones
    /// with no single `field` can never be a data issue. Mirrors web `isFieldDataIssue`.
    private static func isFieldDataIssue(_ ms: Milestone, _ m: Member) -> Bool {
        guard ms.field != nil else { return false }
        if ms.complete(m) { return false }
        let s = (rawValue(of: ms.field, for: m) ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        if !s.isEmpty && !FieldSentinel.isSentinel(s) { return false }
        return true
    }

    /// Build the Golden Hour completion ROWS for one member from a milestone list (defaults to the
    /// integration `all`; pass `needsCategories` to also include temple recommend / endowment /
    /// patriarchal blessing). N/A milestones are OMITTED (not eligible). Each surviving row is
    /// classified done / not-done / issue. The order follows the list. Mirrors web `goldenHourRows`.
    public static func goldenHourRows(_ m: Member, list: [Milestone] = all) -> [GhRow] {
        var rows: [GhRow] = []
        for ms in list {
            // Drop anything that doesn't APPLY: not eligible, or an N/A (not-eligible) field value. A
            // real "Yes" is still kept (expected already lets a completed milestone through).
            if !expected(ms, m) && !ms.complete(m) { continue }
            if ms.complete(m) {
                rows.append(GhRow(milestone: ms, status: .done))
            } else if isFieldDataIssue(ms, m) {
                rows.append(GhRow(milestone: ms, status: .issue))
            } else {
                rows.append(GhRow(milestone: ms, status: .notDone))
            }
        }
        return rows
    }

    /// The milestones this member still NEEDS to do — the not-yet-complete, applicable steps (their
    /// "next steps"). Excludes N/A and completed; includes data-issue rows (a leader should still see
    /// the step is outstanding). Defaults to the integration set. Mirrors web `nextSteps`.
    public static func nextSteps(_ m: Member, list: [Milestone] = all) -> [Milestone] {
        goldenHourRows(m, list: list).filter { $0.status != .done }.map { $0.milestone }
    }
}
