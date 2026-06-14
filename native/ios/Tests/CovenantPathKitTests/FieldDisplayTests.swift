import XCTest
@testable import CovenantPathKit

/// Unit tests for the field DISPLAY CONTRACT (`FieldDisplayLogic`), mirroring web
/// `apps/web/src/logic/fieldDisplay.ts` + `apps/web/src/lib/member.ts`. The whole point: the raw
/// "needs-profile-api" / "blocked: …" sentinel must NEVER leak to a leader — it's a ⚠ data issue,
/// the same as null/empty; "N/A" is a quiet not-eligible state, never a warning; a real value shows
/// verbatim. Regression for the user's "I still see a lot of needs-profile-api" pain.
final class FieldDisplayTests: XCTestCase {

    // MARK: - sentinel recognizer

    func testIsSentinelRecognizesBackendPlaceholders() {
        XCTAssertTrue(FieldSentinel.isSentinel("needs-profile-api"))
        XCTAssertTrue(FieldSentinel.isSentinel("blocked: insufficient calling access"))
        XCTAssertTrue(FieldSentinel.isSentinel("blocked"))
        XCTAssertFalse(FieldSentinel.isSentinel("Yes"))
        XCTAssertFalse(FieldSentinel.isSentinel("No"))
        XCTAssertFalse(FieldSentinel.isSentinel("N/A"))
        XCTAssertFalse(FieldSentinel.isSentinel(""))
        XCTAssertFalse(FieldSentinel.isSentinel(nil))
    }

    // MARK: - the three-way classification

    func testRealValueShowsVerbatim() {
        let d = FieldDisplayLogic.classify("Yes")
        XCTAssertEqual(d.status, .value)
        XCTAssertEqual(d.text, "Yes")
        XCTAssertFalse(d.warn)
        XCTAssertEqual(FieldDisplayLogic.classify("Active").text, "Active")
        XCTAssertEqual(FieldDisplayLogic.classify("6 Feb 2026").text, "6 Feb 2026")
    }

    func testNAIsQuietNeverAWarning() {
        let d = FieldDisplayLogic.classify("N/A")
        XCTAssertEqual(d.status, .na)
        XCTAssertEqual(d.text, "N/A")
        XCTAssertFalse(d.warn)
        // Case-insensitive + whitespace tolerant, like web isNA.
        XCTAssertEqual(FieldDisplayLogic.classify(" n/a ").status, .na)
    }

    func testSentinelIsADataIssueAndNeverLeaksToALeader() {
        let d = FieldDisplayLogic.classify("needs-profile-api", isAdmin: false)
        XCTAssertEqual(d.status, .issue)
        XCTAssertTrue(d.warn)
        // A leader NEVER sees the raw techy string — text is empty (the ⚠ is shown instead).
        XCTAssertEqual(d.text, "")

        let blocked = FieldDisplayLogic.classify("blocked: insufficient calling access", isAdmin: false)
        XCTAssertEqual(blocked.status, .issue)
        XCTAssertEqual(blocked.text, "")
    }

    func testEmptyAndNilAreTheSameDataIssueAsTheSentinel() {
        for v: String? in ["", "   ", nil] {
            let d = FieldDisplayLogic.classify(v)
            XCTAssertEqual(d.status, .issue, "value \(String(describing: v)) should be a data issue")
            XCTAssertTrue(d.warn)
            XCTAssertEqual(d.text, "")   // nothing techy to surface even for an admin
        }
    }

    func testAdminSeesRawSentinelForDiagnosisButNotForEmpty() {
        // Admin keeps the raw sentinel string (to diagnose) — still a warning.
        let sentinel = FieldDisplayLogic.classify("needs-profile-api", isAdmin: true)
        XCTAssertEqual(sentinel.status, .issue)
        XCTAssertTrue(sentinel.warn)
        XCTAssertEqual(sentinel.text, "needs-profile-api")
        // But an empty value has nothing techy to show, even to an admin.
        XCTAssertEqual(FieldDisplayLogic.classify("", isAdmin: true).text, "")
    }

    func testIsDataIssueConvenience() {
        XCTAssertTrue(FieldDisplayLogic.isDataIssue("needs-profile-api"))
        XCTAssertTrue(FieldDisplayLogic.isDataIssue(nil))
        XCTAssertTrue(FieldDisplayLogic.isDataIssue(""))
        XCTAssertFalse(FieldDisplayLogic.isDataIssue("N/A"))   // not-eligible, not an issue
        XCTAssertFalse(FieldDisplayLogic.isDataIssue("Yes"))
    }

    // MARK: - Golden Hour completion ROWS (✓ done / ○ not-done / ⚠ issue; N/A omitted)

    func testGoldenHourRowsClassifyDoneNotDoneAndIssue() {
        let year = Calendar.current.component(.year, from: Date())
        // Adult man, member 2y: Friends done, Calling a genuine "No" (not-done), Has-ministers is the
        // sentinel (data issue).
        let m = Member(baptismDate: "\(year - 2)-01-01", birthDate: "\(year - 30)-01-01", sex: "M",
                       friends: "Yes", calling: "No",
                       ministeringBrothersSisters: "needs-profile-api")
        let rows = Milestones.goldenHourRows(m)
        let byLabel = Dictionary(uniqueKeysWithValues: rows.map { ($0.milestone.label, $0.status) })
        XCTAssertEqual(byLabel["Friends"], .done)
        XCTAssertEqual(byLabel["Calling"], .notDone)         // an honest "No" is NOT a data issue
        XCTAssertEqual(byLabel["Has ministers"], .issue)     // sentinel → ⚠
    }

    func testGoldenHourRowsOmitNAAndIneligible() {
        let year = Calendar.current.component(.year, from: Date())
        // A young girl: priesthood/calling don't apply (ineligible by age/sex) → omitted entirely;
        // never a ⚠, never an N/A row.
        let child = Member(birthDate: "\(year - 8)-01-01", sex: "F")
        let labels = Set(Milestones.goldenHourRows(child).map { $0.milestone.label })
        XCTAssertFalse(labels.contains("Calling"))
        XCTAssertFalse(labels.contains("Aaronic Priesthood"))
        XCTAssertFalse(labels.contains("Melchizedek Priesthood"))
        // Friends + Has ministers DO apply to everyone.
        XCTAssertTrue(labels.contains("Friends"))
        XCTAssertTrue(labels.contains("Has ministers"))
    }

    func testNextStepsAreTheOutstandingApplicableMilestones() {
        let year = Calendar.current.component(.year, from: Date())
        let m = Member(baptismDate: "\(year - 2)-01-01", birthDate: "\(year - 30)-01-01", sex: "F",
                       friends: "Yes", calling: "No",
                       ministeringBrothersSisters: "Yes", ministeringAssignment: "No")
        let steps = Set(Milestones.nextSteps(m).map { $0.label })
        XCTAssertFalse(steps.contains("Friends"))            // done → not a next step
        XCTAssertFalse(steps.contains("Has ministers"))      // done
        XCTAssertTrue(steps.contains("Calling"))             // outstanding
        XCTAssertTrue(steps.contains("Ministering assignment"))
    }
}
