import XCTest
@testable import CovenantPathKit

/// Tests for the ported KPI series/bucketing math (`Kpis`) and freshness helpers — mirroring the
/// behavior of `dashboard_common.dart`. Date-relative so they stay valid over time.
final class KpisTests: XCTestCase {

    private func member(uuid: String, sacramentDates: [String] = [], firstLesson: String? = nil,
                        unit: String = "First Ward", kind: String = "new_member") -> Member {
        var d = MemberDetails()
        if !sacramentDates.isEmpty {
            d.sacrament = sacramentDates.map { .init(label: $0, attended: true, date: $0) }
        }
        d.firstLesson = firstLesson
        return Member(personUUID: uuid, unitName: unit,
                      kind: kind, details: d)
    }

    // MARK: - attendedDates / firstLessonDate extractors

    func testAttendedDatesOnlyCountsAttended() {
        var d = MemberDetails()
        d.sacrament = [
            .init(label: "a", attended: true, date: "2026-05-03"),
            .init(label: "b", attended: false, date: "2026-05-10"),
            .init(label: "c", attended: true, date: "2026-05-17"),
        ]
        let m = Member(personUUID: "x", details: d)
        XCTAssertEqual(Kpis.attendedDates(m).count, 2)
    }

    func testFirstLessonDate() {
        var d = MemberDetails(); d.firstLesson = "2026-04-01"
        let m = Member(personUUID: "y", details: d)
        XCTAssertEqual(Kpis.firstLessonDate(m).count, 1)
        XCTAssertTrue(Kpis.firstLessonDate(Member(personUUID: "z")).isEmpty)
    }

    // MARK: - lessonsWithMember / membersWithMemberLessons

    func testLessonsWithMemberCountsLessonsWithAnyMemberPresent() {
        var d = MemberDetails()
        d.lessons = [
            .init(name: "L1", principles: [.init(name: "p", memberPresent: true, taughtLevel: "1")]),
            .init(name: "L2", principles: [.init(name: "p", memberPresent: false, taughtLevel: "1")]),
            .init(name: "L3", principles: [.init(name: "p", memberPresent: true, taughtLevel: "0")]),
        ]
        let m = Member(personUUID: "a", details: d)
        XCTAssertEqual(Kpis.lessonsWithMember([m]), 2)   // L1 + L3
        let ranked = Kpis.membersWithMemberLessons([m])
        XCTAssertEqual(ranked.first?.count, 2)
    }

    // MARK: - metricData bucketing

    func testMonthSeriesHasFiveWeeklyBuckets() {
        let now = fixedMonday
        // Populate the FIRST (4 weeks ago) AND LAST (this week) bucket so the N9 trim keeps all 5.
        let first = member(uuid: "first", sacramentDates: [ymdStr(daysBefore(28, now))])
        let last = member(uuid: "last", sacramentDates: [ymdStr(now)])
        let (series, events) = Kpis.metricData([first, last], datesOf: Kpis.attendedDates, period: .month, now: now)
        XCTAssertEqual(series.labels.count, 5)            // 5 weeks
        XCTAssertEqual(series.current.count, 5)
        XCTAssertEqual(series.current.last, 1)            // this week
        XCTAssertEqual(series.current.first, 1)           // 4 weeks ago
        XCTAssertEqual(events.count, 2)
    }

    func testYearSeriesHasTwelveMonthlyBuckets() {
        let now = fixedMonday
        // First (11 months ago) AND current month populated → trim keeps the full 12 buckets.
        let first = member(uuid: "first", sacramentDates: [ymdStr(monthsBefore(11, now))])
        let last = member(uuid: "last", sacramentDates: [ymdStr(now)])
        let (series, _) = Kpis.metricData([first, last], datesOf: Kpis.attendedDates, period: .year, now: now)
        XCTAssertEqual(series.labels.count, 12)
        XCTAssertEqual(series.current.last, 1)           // this month
    }

    // MARK: - N9: no 0-padding — collapse/trim to the data span

    func testEmptyWindowCollapsesToEmptySeries() {
        // No data → no padded-0 buckets (the chart shows its empty state, not a flat zero line).
        let none = member(uuid: "none")
        let (month, mEvents) = Kpis.metricData([none], datesOf: Kpis.attendedDates, period: .month, now: fixedMonday)
        XCTAssertTrue(month.isEmpty)
        XCTAssertTrue(mEvents.isEmpty)
        let (year, _) = Kpis.metricData([none], datesOf: Kpis.attendedDates, period: .year, now: fixedMonday)
        XCTAssertTrue(year.labels.isEmpty)
    }

    func testTrimsToDataSpanWhenLeadingBucketsEmpty() {
        // Only this week has data → MONTH collapses to that single bucket (not 5, four of them 0).
        let m = member(uuid: "m1", sacramentDates: [ymdStr(fixedMonday)])
        let (series, events) = Kpis.metricData([m], datesOf: Kpis.attendedDates, period: .month, now: fixedMonday)
        XCTAssertEqual(series.labels.count, 1)
        XCTAssertEqual(series.current.last, 1)
        XCTAssertEqual(events.first?.bucket, 0)           // event rebucketed to the trimmed index
    }

    func testBaptismsByMonthTrimsToSpan() {
        // Two baptisms three months apart inside a 12-month window → 4 contiguous months (Mar…Jun),
        // not the full 12 with leading 0s. Best month + total still reflect the data.
        let now = fixedMonday // 2026-06-01
        let a = Member(personUUID: "a", unitName: "A", baptismDate: "2026-03-15", kind: "convert")
        let b = Member(personUUID: "b", unitName: "A", baptismDate: "2026-06-01", kind: "convert")
        let r = Kpis.baptismsByMonth([a, b], window: .m12, now: now)
        XCTAssertEqual(r.labels, ["Mar", "Apr", "May", "Jun"])
        XCTAssertEqual(r.counts, [1, 0, 0, 1])
        XCTAssertEqual(r.total, 2)
        XCTAssertEqual(r.events.map { $0.bucket }.sorted(), [0, 3]) // rebucketed to the trimmed range
    }

    func testUniquePeoplePerBucketCountedOnce() {
        // Same member attending twice in the same week → counts once in that bucket.
        let m = member(uuid: "dup", sacramentDates: [isoDaysAgo(1), isoDaysAgo(2)])
        let (series, _) = Kpis.metricData([m], datesOf: Kpis.attendedDates, period: .month)
        XCTAssertEqual(series.current.last, 1)
    }

    func testAllEmptyWhenNoEvents() {
        let m = member(uuid: "none")
        let (series, events) = Kpis.metricData([m], datesOf: Kpis.attendedDates, period: .all)
        XCTAssertTrue(series.isEmpty)
        XCTAssertTrue(events.isEmpty)
    }

    func testUnitCompletionRanksByPct() {
        // Two units: one fully has Friends, one doesn't (Friends applies to everyone).
        let good = Member(personUUID: "g", unitName: "A", friends: "Yes", kind: "new_member")
        let bad = Member(personUUID: "b", unitName: "B", friends: "No", kind: "new_member")
        let ranked = Kpis.unitCompletion([good, bad])
        XCTAssertEqual(ranked.first?.unit, "A")
        XCTAssertGreaterThan(ranked.first!.pct, ranked.last!.pct)
    }

    // MARK: - Freshness

    func testFreshnessAgo() {
        let now = Date()
        XCTAssertEqual(Freshness.ago(iso(now.addingTimeInterval(-3600)), now: now), "1h ago")
        XCTAssertEqual(Freshness.ago(iso(now.addingTimeInterval(-120)), now: now), "2m ago")
        XCTAssertEqual(Freshness.ago(iso(now.addingTimeInterval(-2 * 86400)), now: now), "2d ago")
    }

    func testStaleness() {
        let now = Date()
        XCTAssertEqual(Freshness.staleness(iso(now), now: now), .fresh)
        XCTAssertEqual(Freshness.staleness(iso(now.addingTimeInterval(-3 * 86400)), now: now), .amber)
        XCTAssertEqual(Freshness.staleness(iso(now.addingTimeInterval(-20 * 86400)), now: now), .red)
        XCTAssertEqual(Freshness.staleness(nil, now: now), .red)
    }

    // MARK: - helpers

    private func isoDaysAgo(_ d: Int) -> String {
        let date = Calendar.current.date(byAdding: .day, value: -d, to: Date())!
        let c = Calendar.current.dateComponents([.year, .month, .day], from: date)
        return String(format: "%04d-%02d-%02d", c.year!, c.month!, c.day!)
    }
    /// A fixed Monday (2026-06-01) so the weekly/monthly windows are deterministic (N9 trim tests).
    private var fixedMonday: Date {
        var c = DateComponents(); c.year = 2026; c.month = 6; c.day = 1
        return Calendar.current.date(from: c)!
    }
    private func ymdStr(_ d: Date) -> String {
        let c = Calendar.current.dateComponents([.year, .month, .day], from: d)
        return String(format: "%04d-%02d-%02d", c.year!, c.month!, c.day!)
    }
    private func daysBefore(_ n: Int, _ d: Date) -> Date { Calendar.current.date(byAdding: .day, value: -n, to: d)! }
    private func monthsBefore(_ n: Int, _ d: Date) -> Date { Calendar.current.date(byAdding: .month, value: -n, to: d)! }
    private func iso(_ d: Date) -> String {
        let f = ISO8601DateFormatter(); f.formatOptions = [.withInternetDateTime]
        return f.string(from: d)
    }
}
