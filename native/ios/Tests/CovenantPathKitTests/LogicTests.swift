import XCTest
@testable import CovenantPathKit

/// Unit tests for the pure, ported business logic. These mirror the rules in `golden_hour.dart`
/// (and the spec). They run on macOS via `swift test` without a simulator. Date-dependent tests are
/// written relative to "now" so they stay valid over time.
final class LogicTests: XCTestCase {

    // MARK: - date parsing

    func testISODate() {
        let d = MemberDate.parse("2026-02-06")
        let c = Calendar.current.dateComponents([.year, .month, .day], from: d!)
        XCTAssertEqual(c.year, 2026); XCTAssertEqual(c.month, 2); XCTAssertEqual(c.day, 6)
    }

    func testDayMonthYear() {
        let d = MemberDate.parse("6 Feb 2026")
        let c = Calendar.current.dateComponents([.year, .month, .day], from: d!)
        XCTAssertEqual(c.year, 2026); XCTAssertEqual(c.month, 2); XCTAssertEqual(c.day, 6)
    }

    func testSlashDateFullYear() {
        let d = MemberDate.parse("2/6/2026")
        let c = Calendar.current.dateComponents([.month, .day, .year], from: d!)
        XCTAssertEqual(c.month, 2); XCTAssertEqual(c.day, 6); XCTAssertEqual(c.year, 2026)
    }

    func testSlashDateTwoDigitYear() {
        let d = MemberDate.parse("2/6/26")
        XCTAssertEqual(Calendar.current.component(.year, from: d!), 2026)
    }

    func testSentinelsAndEmptyAreNil() {
        XCTAssertNil(MemberDate.parse("N/A"))
        XCTAssertNil(MemberDate.parse("needs-profile-api"))
        XCTAssertNil(MemberDate.parse("blocked: insufficient calling access"))
        XCTAssertNil(MemberDate.parse(""))
        XCTAssertNil(MemberDate.parse("   "))
        XCTAssertNil(MemberDate.parse(nil))
        XCTAssertNil(MemberDate.parse("not a date"))
    }

    func testYearOf() {
        XCTAssertEqual(MemberDate.yearOf("born 1990 something"), 1990)
        XCTAssertEqual(MemberDate.yearOf("1985-03-02"), 1985)
        XCTAssertNil(MemberDate.yearOf("no digits"))
    }

    // MARK: - eligibility

    private func member(birthYear: Int? = nil, sex: String = "M",
                        baptismDaysAgo: Int? = nil, membership: String? = nil) -> Member {
        let birth = birthYear.map { "\($0)-06-15" }
        let baptismISO: String? = baptismDaysAgo.map {
            let d = Calendar.current.date(byAdding: .day, value: -$0, to: Date())!
            let c = Calendar.current.dateComponents([.year, .month, .day], from: d)
            return String(format: "%04d-%02d-%02d", c.year!, c.month!, c.day!)
        }
        return Member(name: "Test Person", baptismDate: baptismISO, birthDate: birth, sex: sex,
                      membershipDuration: membership)
    }

    func testTurnsAtLeastByYear() {
        let year = Calendar.current.component(.year, from: Date())
        // Someone turning exactly 12 this year (born year-12) is eligible.
        XCTAssertTrue(Milestones.turnsAtLeast(member(birthYear: year - 12), 12))
        // Someone turning 11 this year is not yet eligible for a 12+ gate.
        XCTAssertFalse(Milestones.turnsAtLeast(member(birthYear: year - 11), 12))
        // Unknown birth → not eligible.
        XCTAssertFalse(Milestones.turnsAtLeast(member(birthYear: nil), 12))
    }

    func testMemberOneYearPlusByBaptism() {
        XCTAssertTrue(Milestones.memberOneYearPlus(member(baptismDaysAgo: 400)))
        XCTAssertFalse(Milestones.memberOneYearPlus(member(baptismDaysAgo: 100)))
    }

    func testMemberOneYearPlusByDuration() {
        XCTAssertTrue(Milestones.memberOneYearPlus(member(membership: "Member for 2 years")))
        XCTAssertFalse(Milestones.memberOneYearPlus(member(membership: "Member for 8 months")))
    }

    func testMelchizedekEligibilityRequiresMaleAdultAndTenure() {
        let year = Calendar.current.component(.year, from: Date())
        let mp = Milestones.all.first { $0.label == "Melchizedek Priesthood" }!
        // Male, 25 now (born year-25), member 2 years → eligible.
        let ok = Member(birthDate: "\(year - 25)-01-01", sex: "M", membershipDuration: "Member for 2 years")
        XCTAssertTrue(mp.eligible(ok))
        // Female → not eligible.
        let female = Member(birthDate: "\(year - 25)-01-01", sex: "F", membershipDuration: "Member for 2 years")
        XCTAssertFalse(mp.eligible(female))
        // Male but only 17 → not eligible.
        let young = Member(birthDate: "\(year - 17)-01-01", sex: "M", membershipDuration: "Member for 2 years")
        XCTAssertFalse(mp.eligible(young))
    }

    func testApplicableExcludesIneligible() {
        // A young girl: Friends + Has ministers apply to everyone; age/sex-gated ones don't.
        let year = Calendar.current.component(.year, from: Date())
        let child = Member(birthDate: "\(year - 8)-01-01", sex: "F")
        let labels = Set(Milestones.applicable(to: child).map(\.label))
        XCTAssertTrue(labels.contains("Friends"))
        XCTAssertTrue(labels.contains("Has ministers"))
        XCTAssertFalse(labels.contains("Calling"))            // needs 12+
        XCTAssertFalse(labels.contains("Aaronic Priesthood")) // male + 12+
    }

    // MARK: - completion math (eligible-only)

    func testCompletionIsEligibleOnly() {
        let year = Calendar.current.component(.year, from: Date())
        let calling = Milestones.all.first { $0.label == "Calling" }!
        let rows = [
            Member(calling: "Yes", birthDate: "\(year - 30)-01-01", sex: "M"),  // eligible, done
            Member(calling: "No", birthDate: "\(year - 30)-01-01", sex: "M"),   // eligible, not done
            Member(calling: "No", birthDate: "\(year - 8)-01-01", sex: "F"),    // ineligible (too young)
        ]
        let c = Milestones.completion(calling, in: rows)
        XCTAssertEqual(c.eligible, 2)   // the child is excluded
        XCTAssertEqual(c.done, 1)
        XCTAssertEqual(Milestones.missing(calling, in: rows).count, 1)
    }

    // MARK: - detail-view eligibility + Needs categories (status-sections work)

    func testEndowmentDisplayGatesIneligibleToNA() {
        let year = Calendar.current.component(.year, from: Date())
        // Adult (30), member 3yr → eligible: a "No" stays "No".
        XCTAssertEqual(Milestones.endowmentDisplay(
            Member(baptismDate: "\(year - 3)-01-01", birthDate: "\(year - 30)-01-01", livingOrdinance: "No")), "No")
        // <1-year member → ineligible: "No" becomes "N/A".
        XCTAssertEqual(Milestones.endowmentDisplay(
            Member(baptismDate: "\(year)-01-01", birthDate: "\(year - 30)-01-01", livingOrdinance: "No")), "N/A")
        // A real "Yes" is always kept (even for a child).
        XCTAssertEqual(Milestones.endowmentDisplay(
            Member(birthDate: "\(year - 8)-01-01", livingOrdinance: "Yes")), "Yes")
    }

    func testCompletionOfFractionEligibleOnly() {
        let year = Calendar.current.component(.year, from: Date())
        // Adult female, member 3yr → applicable: Friends, Calling, Has-ministers, Ministering-assignment.
        let none = Member(baptismDate: "\(year - 3)-01-01", birthDate: "\(year - 30)-01-01", sex: "F")
        XCTAssertEqual(Milestones.completionOf(none), 0.0, accuracy: 1e-9)
        let allDone = Member(baptismDate: "\(year - 3)-01-01", birthDate: "\(year - 30)-01-01", sex: "F",
                             friends: "Yes", calling: "Yes",
                             ministeringBrothersSisters: "Yes", ministeringAssignment: "Yes")
        XCTAssertEqual(Milestones.completionOf(allDone), 1.0, accuracy: 1e-9)
    }

    func testNeedsCategoriesAddLongerHorizonCovenants() {
        let labels = Set(Milestones.needsCategories.map(\.label))
        XCTAssertTrue(labels.contains("Temple Recommend"))
        XCTAssertTrue(labels.contains("Endowment"))
        XCTAssertTrue(labels.contains("Patriarchal Blessing"))
        let year = Calendar.current.component(.year, from: Date())
        let en = Milestones.needsCategories.first { $0.label == "Endowment" }!
        // Eligible adult 1yr+ with no living ordinance is "missing" endowment.
        let adult = Member(baptismDate: "\(year - 3)-01-01", birthDate: "\(year - 30)-01-01", livingOrdinance: "No")
        XCTAssertTrue(en.eligible(adult) && !en.complete(adult))
        // A child is not eligible for it.
        XCTAssertFalse(en.eligible(Member(birthDate: "\(year - 8)-01-01")))
    }

    // MARK: - org bucket

    func testResponsibleOrgFirstYearIsWML() {
        let m = member(baptismDaysAgo: 30, sex: "M")
        XCTAssertEqual(Org.responsible(for: m), .wml)
    }

    func testResponsibleOrgAfterYearBySex() {
        XCTAssertEqual(Org.responsible(for: member(baptismDaysAgo: 800, sex: "M")), .eq)
        XCTAssertEqual(Org.responsible(for: member(baptismDaysAgo: 800, sex: "F")), .rs)
    }

    func testResponsibleOrgNilWithoutBaptismDate() {
        XCTAssertNil(Org.responsible(for: Member(name: "No Date")))
    }

    func testOrgBoundaryAt12Months() {
        // 11 months → WML; 13 months → EQ (men). 30.44 days/month, floored.
        XCTAssertEqual(Org.responsible(for: member(baptismDaysAgo: Int(30.44 * 11), sex: "M")), .wml)
        XCTAssertEqual(Org.responsible(for: member(baptismDaysAgo: Int(30.44 * 13), sex: "M")), .eq)
    }

    // MARK: - org filter toggle guard

    func testOrgFilterCannotDeselectLast() {
        // Uses the pure `Org.toggleFilter` (the SwiftUI `OrgFilterBar.toggle` delegates to it), so the
        // guard is testable on macOS without UIKit.
        var set: Set<OrgBucket> = [.wml]
        Org.toggleFilter(.wml, in: &set)
        XCTAssertEqual(set, [.wml])  // unchanged — can't empty it
        set = [.wml, .eq]
        Org.toggleFilter(.wml, in: &set)
        XCTAssertEqual(set, [.eq])
        Org.toggleFilter(.rs, in: &set)
        XCTAssertEqual(set, [.eq, .rs])
    }

    // MARK: - recency window

    func testRecencyWindows() {
        XCTAssertTrue(Recency.all.contains(Member(baptismDate: "2000-01-01")))
        XCTAssertTrue(Recency.week.contains(member(baptismDaysAgo: 3)))
        XCTAssertFalse(Recency.week.contains(member(baptismDaysAgo: 30)))
        XCTAssertTrue(Recency.month.contains(member(baptismDaysAgo: 20)))
        XCTAssertTrue(Recency.year.contains(member(baptismDaysAgo: 300)))
        // No baptism date fails any bounded window but passes "all".
        let noDate = Member(name: "x")
        XCTAssertFalse(Recency.week.contains(noDate))
        XCTAssertTrue(Recency.all.contains(noDate))
    }

    // MARK: - initials & elapsed

    func testInitials() {
        XCTAssertEqual(Initials.of("Smith, John"), "SJ")  // comma stripped, first+last
        XCTAssertEqual(Initials.of("Madonna"), "M")
        XCTAssertEqual(Initials.of(""), "?")
        XCTAssertEqual(Initials.of(nil), "?")
    }

    func testMonthsDaysAgoFutureIsEmpty() {
        let future = Calendar.current.date(byAdding: .day, value: 10, to: Date())
        XCTAssertEqual(Elapsed.monthsDaysAgo(future), "")
        XCTAssertEqual(Elapsed.monthsDaysAgo(nil), "")
    }
}
