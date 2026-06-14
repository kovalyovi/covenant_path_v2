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
        return Member(name: "Test Person", baptismDate: baptismISO, birthDate: birth,
                      membershipDuration: membership, sex: sex)
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
        let ok = Member(birthDate: "\(year - 25)-01-01", membershipDuration: "Member for 2 years", sex: "M")
        XCTAssertTrue(mp.eligible(ok))
        // Female → not eligible.
        let female = Member(birthDate: "\(year - 25)-01-01", membershipDuration: "Member for 2 years", sex: "F")
        XCTAssertFalse(mp.eligible(female))
        // Male but only 17 → not eligible.
        let young = Member(birthDate: "\(year - 17)-01-01", membershipDuration: "Member for 2 years", sex: "M")
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
            Member(birthDate: "\(year - 30)-01-01", sex: "M", calling: "Yes"),  // eligible, done
            Member(birthDate: "\(year - 30)-01-01", sex: "M", calling: "No"),   // eligible, not done
            Member(birthDate: "\(year - 8)-01-01", sex: "F", calling: "No"),    // ineligible (too young)
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
                             ministeringBrothersSisters: "Yes", ministeringAssignment: "Yes",
                             familyNamePrepared: "Yes", firstTempleVisit: "Yes")
        XCTAssertEqual(Milestones.completionOf(allDone), 1.0, accuracy: 1e-9)
    }

    func testTempleExperienceValueAndDisplay() {
        let year = Calendar.current.component(.year, from: Date())
        // Flat column (filled by the daily sync) wins.
        XCTAssertEqual(Milestones.firstTempleVisitValue(Member(firstTempleVisit: "Yes")), "Yes")
        // Sentinel/empty flat value falls back to details.templeExperiences.
        var d = MemberDetails()
        d.templeExperiences = [
            .init(name: "Prepare a Family Name for the Temple", done: false),
            .init(name: "Perform Baptisms for Deceased Ancestors", done: true),
        ]
        let m = Member(birthDate: "\(year - 20)-01-01", firstTempleVisit: "needs-profile-api",
                       details: d)
        XCTAssertEqual(Milestones.firstTempleVisitValue(m), "Yes")
        XCTAssertEqual(Milestones.familyNameValue(m), "No")
        // Under-12 "No" displays as N/A (can't do proxy baptisms yet); a real "Yes" is kept.
        XCTAssertEqual(Milestones.firstTempleVisitDisplay(
            Member(birthDate: "\(year - 8)-01-01", firstTempleVisit: "No")), "N/A")
        XCTAssertEqual(Milestones.firstTempleVisitDisplay(
            Member(birthDate: "\(year - 8)-01-01", firstTempleVisit: "Yes")), "Yes")
        // Eligible from the year someone turns 12 (by-year rule), like calling.
        let fn = Milestones.all.first { $0.abbr == "FN" }!
        XCTAssertTrue(fn.eligible(Member(birthDate: "\(year - 12)-01-01")))
        XCTAssertFalse(fn.eligible(Member(birthDate: "\(year - 8)-01-01")))
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
        let m = member(sex: "M", baptismDaysAgo: 30)
        XCTAssertEqual(Org.responsible(for: m), .wml)
    }

    func testResponsibleOrgAfterYearBySex() {
        XCTAssertEqual(Org.responsible(for: member(sex: "M", baptismDaysAgo: 800)), .eq)
        XCTAssertEqual(Org.responsible(for: member(sex: "F", baptismDaysAgo: 800)), .rs)
    }

    func testResponsibleOrgNilWithoutBaptismDate() {
        XCTAssertNil(Org.responsible(for: Member(name: "No Date")))
    }

    func testOrgBoundaryAt12Months() {
        // 11 months → WML; 13 months → EQ (men). 30.44 days/month, floored.
        XCTAssertEqual(Org.responsible(for: member(sex: "M", baptismDaysAgo: Int(30.44 * 11))), .wml)
        XCTAssertEqual(Org.responsible(for: member(sex: "M", baptismDaysAgo: Int(30.44 * 13))), .eq)
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

    private func daysAgo(_ n: Int) -> Date {
        Calendar.current.date(byAdding: .day, value: -n, to: Date())!
    }

    func testBaptismElapsedMonthsOnlyPastAMonth() {
        // ≥1 month in → months only (no trailing "days"); under a month → days.
        let threeMonths = Elapsed.baptismElapsed(daysAgo(100))
        XCTAssertTrue(threeMonths.contains("month"))
        XCTAssertFalse(threeMonths.contains("day"))
        XCTAssertEqual(Elapsed.baptismElapsed(daysAgo(5)), "5 days")
        XCTAssertEqual(Elapsed.baptismElapsed(nil), "")
        XCTAssertEqual(Elapsed.baptismElapsed(Calendar.current.date(byAdding: .day, value: 10, to: Date())), "")
    }

    func testTenureUsesYearsAndDropsZeroParts() {
        // >2 months → years/months format (never days, never "0 years").
        let t = Elapsed.tenure(daysAgo(800)) // ~2 years 2 months
        XCTAssertTrue(t.contains("year"))
        XCTAssertFalse(t.contains("day"))
        XCTAssertFalse(t.contains("0 year"))
        XCTAssertFalse(t.contains("0 month"))
        // Under 2 months → month+days (reuses monthsDaysAgo).
        XCTAssertEqual(Elapsed.tenure(daysAgo(5)), "5 days")
        XCTAssertEqual(Elapsed.tenure(nil), "")
        XCTAssertEqual(Elapsed.tenure(Calendar.current.date(byAdding: .day, value: 10, to: Date())), "")
    }

    // MARK: - sacrament attendance health (#1e / #10b)

    func testAttendanceBucketLevels() {
        XCTAssertEqual(Kpis.attendanceBucket(nil).level, .unknown)
        XCTAssertEqual(Kpis.attendanceBucket(nil).label, "—")
        XCTAssertEqual(Kpis.attendanceBucket((attended: 8, total: 8)).level, .great)
        XCTAssertEqual(Kpis.attendanceBucket((attended: 7, total: 8)).level, .great)
        XCTAssertEqual(Kpis.attendanceBucket((attended: 5, total: 8)).level, .fair)
        XCTAssertEqual(Kpis.attendanceBucket((attended: 2, total: 8)).level, .poor)
        let none = Kpis.attendanceBucket((attended: 0, total: 8))
        XCTAssertEqual(none.level, .none)
        XCTAssertTrue(none.bold)                                   // 0-of-window is the only BOLD signal
        XCTAssertEqual(none.label, "0/8")
        XCTAssertFalse(Kpis.attendanceBucket((attended: 7, total: 8)).bold)
    }

    func testSacramentWindowTakesEightNewest() {
        // 10 weekly entries, the 8 newest all attended, the 2 oldest missed; shuffled order.
        let cal = Calendar.current
        var entries: [MemberDetails.SacramentEntry] = []
        for i in 0..<10 {
            let d = cal.date(byAdding: .day, value: -i * 7, to: Date())!
            let c = cal.dateComponents([.year, .month, .day], from: d)
            let iso = String(format: "%04d-%02d-%02d", c.year!, c.month!, c.day!)
            entries.append(.init(attended: i < 8, date: iso))
        }
        let win = Kpis.sacramentWindow(entries.shuffled())!
        XCTAssertEqual(win.total, 8)     // capped at the window size
        XCTAssertEqual(win.attended, 8)  // the 8 newest were all attended
        XCTAssertNil(Kpis.sacramentWindow(nil))
        XCTAssertNil(Kpis.sacramentWindow([]))
    }

    // MARK: - #8d per-unit Golden Hour rollup

    func testUnitGoldenHourRollup() {
        let year = Calendar.current.component(.year, from: Date())
        // Arguments stay in the init's declaration order (Swift requires it): …sex, friends, aaronic,
        // melchizedek, calling, ministering*, familyName, firstTempleVisit.
        let a1 = Member(name: "A1", unitName: "Ward A", baptismDate: "\(year - 2)-01-01",
                        birthDate: "\(year - 30)-01-01", sex: "M", friends: "Yes",
                        aaronicPriesthood: "Yes", melchizedekPriesthood: "Yes", calling: "Yes",
                        ministeringBrothersSisters: "Yes", ministeringAssignment: "Yes",
                        familyNamePrepared: "Yes", firstTempleVisit: "Yes")
        let a2 = Member(name: "A2", unitName: "Ward A", baptismDate: "\(year - 2)-01-01",
                        birthDate: "\(year - 30)-01-01", sex: "M", friends: "Yes",
                        aaronicPriesthood: "Yes", melchizedekPriesthood: "Yes", calling: "No",
                        ministeringBrothersSisters: "Yes", ministeringAssignment: "Yes",
                        familyNamePrepared: "Yes", firstTempleVisit: "Yes") // 7/8
        let b1 = Member(name: "B1", unitName: "Ward B", baptismDate: "\(year - 2)-01-01",
                        birthDate: "\(year - 30)-01-01", sex: "M", friends: "Yes",
                        aaronicPriesthood: "Yes", melchizedekPriesthood: "Yes", calling: "Yes",
                        ministeringBrothersSisters: "Yes", ministeringAssignment: "Yes",
                        familyNamePrepared: "Yes", firstTempleVisit: "Yes")
        let out = Milestones.unitGoldenHour([a1, a2, b1])
        XCTAssertEqual(out.first?.unit, "Ward A") // ranked by people desc (2 > 1)
        let a = out.first { $0.unit == "Ward A" }!
        XCTAssertEqual(a.people, 2)
        XCTAssertEqual(a.fullyComplete, 1)  // only a1 has every applicable milestone complete
        XCTAssertEqual(a.itemsDone, 15)     // 8 + 7
        XCTAssertEqual(a.itemsTotal, 16)    // 8 + 8
        let b = out.first { $0.unit == "Ward B" }!
        XCTAssertEqual(b.fullyComplete, 1)
        XCTAssertEqual(b.itemsTotal, 8)
    }

    // MARK: - leadership / staffing gaps (#12)

    func testStaffingGapsAndHolders() {
        let full = [
            StaffingMember(position: "Ward Mission Leader", person: "Jane"),
            StaffingMember(position: "Ward Missionary", person: "A"),
            StaffingMember(position: "Ward Missionary", person: "B"),
            StaffingMember(position: "Elders Quorum President", person: "C"),
            StaffingMember(position: "Relief Society President", person: "D"),
        ]
        XCTAssertEqual(Staffing.gapCount(full), 0)
        XCTAssertEqual(Staffing.gaps(full).first { $0.key == "wml" }?.holders, ["Jane"])

        let short = [
            StaffingMember(position: "Assistant Ward Mission Leader", person: "X"), // must NOT fill WML
            StaffingMember(position: "Ward Missionary", person: "Y"),               // only 1 < 2
            StaffingMember(position: "Elders Quorum First Counselor", person: "Z"),  // counselor ≠ president
        ]
        let byKey = Dictionary(uniqueKeysWithValues: Staffing.gaps(short).map { ($0.key, $0) })
        XCTAssertFalse(byKey["wml"]!.ok)
        XCTAssertFalse(byKey["ward_missionaries"]!.ok)
        XCTAssertFalse(byKey["eq_pres"]!.ok)
        XCTAssertFalse(byKey["rs_pres"]!.ok)
        XCTAssertEqual(Staffing.gapCount(short), 4)
    }

    // MARK: - notes index (mirrors web src/test/notes.test.ts)

    private func noteRow(_ uuid: String?, _ body: String?, _ at: String?) -> MemberNoteRow {
        MemberNoteRow(memberPersonUUID: uuid, body: body, createdAt: at)
    }

    func testNotesIndexKeepsNewestAndCounts() {
        let idx = NotesIndex.build([
            noteRow("a", "older", "2026-06-01T10:00:00+00:00"),
            noteRow("a", "newest", "2026-06-09T10:00:00+00:00"),
            noteRow("a", "middle", "2026-06-05T10:00:00+00:00"),
            noteRow("b", "only one", "2026-06-02T10:00:00+00:00"),
        ])
        XCTAssertEqual(idx["a"], NoteSummary(count: 3, latest: "newest", latestAt: "2026-06-09T10:00:00+00:00"))
        XCTAssertEqual(idx["b"], NoteSummary(count: 1, latest: "only one", latestAt: "2026-06-02T10:00:00+00:00"))
    }

    func testNotesIndexOrderIndependent() {
        let rows = [
            noteRow("a", "second", "2026-06-08T10:00:00+00:00"),
            noteRow("a", "first", "2026-06-07T10:00:00+00:00"),
        ]
        XCTAssertEqual(NotesIndex.build(rows)["a"]?.latest, "second")
        XCTAssertEqual(NotesIndex.build(rows.reversed())["a"]?.latest, "second")
    }

    func testNotesIndexSkipsBlankAndMissingUUID() {
        let idx = NotesIndex.build([
            noteRow("", "no uuid", "2026-06-01T00:00:00Z"),
            noteRow("a", "   ", "2026-06-01T00:00:00Z"),
            noteRow("a", nil, "2026-06-01T00:00:00Z"),
            noteRow(nil, "x", "2026-06-01T00:00:00Z"),
        ])
        XCTAssertTrue(idx.isEmpty)
    }

    func testNotesIndexMissingCreatedAt() {
        let idx = NotesIndex.build([
            noteRow("a", "undated", nil),
            noteRow("a", "dated", "2026-06-01T00:00:00Z"),
        ])
        XCTAssertEqual(idx["a"]?.count, 2)
        XCTAssertEqual(idx["a"]?.latest, "dated")
    }
}
