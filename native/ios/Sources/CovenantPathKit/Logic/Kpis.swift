import Foundation

/// KPI series/bucketing math — a faithful, pure-Swift port of the Dart helpers in
/// `apps/viewer/lib/views/dashboard_common.dart` + `kpis_view.dart`. UI-free and unit-tested so the
/// KPIs tab (Swift Charts) renders exactly the same numbers as the Flutter `_KpiView`.
///
/// The three time periods mirror Flutter exactly:
///   - `.month` — the 5 WEEKS ending this week  (weekly buckets, Monday-anchored)
///   - `.year`  — the 12 MONTHS ending this month(monthly buckets)
///   - `.all`   — first data → now, grouped by MONTH (≤36 months span) or by YEAR (longer)
/// Buckets with no events render as zeros. The `prev` overlay is the immediately-preceding equal span.
public enum KpiPeriod: String, CaseIterable, Identifiable, Sendable {
    case month, ytd, year, all, custom
    public var id: String { rawValue }

    public var label: String {
        switch self {
        case .month: return "Month"
        case .ytd: return "YTD"
        case .year: return "Year"
        case .all: return "All"
        case .custom: return "Custom"
        }
    }

    /// (prior-window label, latest-window label) for the compare big-stats — mirrors `_compareLabels`.
    public var compareLabels: (prev: String, latest: String) {
        switch self {
        case .month: return ("Last month", "This month")
        case .ytd: return ("Last year", "This year") // YTD totals: this year vs same period last year
        case .year: return ("Last year", "This year")
        case .custom: return ("Last year", "This year") // same range, one year earlier
        case .all: return ("Prev. month", "This month")
        }
    }
}

/// One chart series: the current window's per-bucket unique-people counts ([current]) overlaid on
/// the immediately-preceding equal-length window ([prev], position-aligned; empty for `.all`/none).
public struct KpiSeries: Sendable {
    public var labels: [String]
    public var current: [Double]
    public var prev: [Double]
    public init(labels: [String] = [], current: [Double] = [], prev: [Double] = []) {
        self.labels = labels; self.current = current; self.prev = prev
    }
    public var isEmpty: Bool { current.isEmpty }
}

/// One matching event for a drill-down: a member counted toward a metric on a date, mapped to the
/// displayed-window bucket index (its x-position). Port of `_Ev`.
public struct KpiEvent: Identifiable, Sendable {
    public let member: Member
    public let date: Date
    public let bucket: Int
    public init(member: Member, date: Date, bucket: Int) {
        self.member = member; self.date = date; self.bucket = bucket
    }
    public var id: String { "\(member.id)|\(date.timeIntervalSince1970)|\(bucket)" }
}

/// #1/#2: window for the Baptisms-by-month stat (year-to-date / trailing 12 / 24 / all-time).
public enum BaptismWindow: String, CaseIterable, Identifiable, Sendable {
    case ytd, m12, m24, all
    public var id: String { rawValue }
    public var label: String {
        switch self {
        case .ytd: return "YTD"
        case .m12: return "12 mo"
        case .m24: return "24 mo"
        case .all: return "All"
        }
    }
}

/// #1/#2: monthly baptism counts over a window + the best month (named) + total in-window.
public struct BaptismsByMonth: Sendable {
    public var labels: [String]
    public var counts: [Double]
    public var events: [KpiEvent]
    public var bestLabel: String?
    public var bestCount: Int
    public var total: Int
}

public enum Kpis {

    // MARK: - calendar helpers (port of _dayOnly / _weekStart)

    static let cal = MemberDate.cal   // cached (was a computed var allocating a fresh snapshot per access)

    static func dayOnly(_ d: Date) -> Date { cal.startOfDay(for: d) }

    /// Monday-anchored week start, matching Dart's `d.subtract(Duration(days: d.weekday - 1))`
    /// where Dart weekday is Mon=1…Sun=7.
    static func weekStart(_ d: Date) -> Date {
        let day = dayOnly(d)
        // Swift weekday: Sun=1…Sat=7. Convert to Dart's Mon=1…Sun=7.
        let swWeekday = cal.component(.weekday, from: day)
        let dartWeekday = ((swWeekday + 5) % 7) + 1  // Sun(1)->7, Mon(2)->1, …, Sat(7)->6
        return cal.date(byAdding: .day, value: -(dartWeekday - 1), to: day) ?? day
    }

    static func ymd(_ d: Date) -> (y: Int, m: Int, d: Int) {
        let c = cal.dateComponents([.year, .month, .day], from: d)
        return (c.year ?? 0, c.month ?? 0, c.day ?? 0)
    }

    /// Build a local date from a (year, month) — month may be out of 1...12 and is normalized,
    /// mirroring Dart's `DateTime(year, month, 1)` overflow behavior.
    static func monthDate(year: Int, month: Int) -> Date {
        var c = DateComponents(); c.year = year; c.month = month; c.day = 1
        return cal.date(from: c) ?? Date()
    }

    // MARK: - bucket key (port of _bucketKey)

    static func bucketKey(_ dt: Date, _ p: KpiPeriod, allByYear: Bool) -> Int {
        switch p {
        case .month:
            let w = ymd(weekStart(dt))
            return w.y * 10000 + w.m * 100 + w.d
        case .ytd, .year, .custom:
            let c = ymd(dt)
            return c.y * 100 + c.m
        case .all:
            let c = ymd(dt)
            return allByYear ? c.y : c.y * 100 + c.m
        }
    }

    // MARK: - window buckets (port of _windowBuckets)

    /// Ordered (key, label) buckets of the window ending `today`, shifted back `shift` windows.
    /// `.all` is data-driven (handled in `metricData`) so returns empty here.
    static func windowBuckets(_ p: KpiPeriod, today: Date, shift: Int,
                              custom: (start: Date, end: Date)? = nil) -> [(key: Int, label: String)] {
        switch p {
        case .month:
            let end = cal.date(byAdding: .day, value: -(shift * 5 * 7), to: weekStart(today)) ?? today
            var out: [(Int, String)] = []
            for i in stride(from: 4, through: 0, by: -1) {
                let w = cal.date(byAdding: .day, value: -(i * 7), to: end) ?? end
                let c = ymd(w)
                out.append((c.y * 10000 + c.m * 100 + c.d, mdLabel(w)))
            }
            return out
        case .year:
            let t = ymd(today)
            var out: [(Int, String)] = []
            for i in stride(from: 11, through: 0, by: -1) {
                let m = monthDate(year: t.y, month: t.m - shift * 12 - i)
                let c = ymd(m)
                out.append((c.y * 100 + c.m, monthAbbrev(m)))
            }
            return out
        case .ytd:
            // Calendar year-to-date: Jan..current month of (this year − shift). shift=1 → last year's
            // same Jan..now span, position-aligned, so "Compare to previous" is year-over-year.
            let t = ymd(today)
            let y = t.y - shift
            var out: [(Int, String)] = []
            for m in 1...t.m {
                out.append((y * 100 + m, monthAbbrev(monthDate(year: y, month: m))))
            }
            return out
        case .custom:
            // #7: monthly buckets from start..end, shifted back `shift` YEARS so the compare overlay
            // is the same calendar range one year earlier (year-over-year).
            guard let custom else { return [] }
            let s = ymd(custom.start), e = ymd(custom.end)
            var out: [(Int, String)] = []
            var y = s.y - shift
            var mo = s.m
            let endY = e.y - shift, endMo = e.m
            while y < endY || (y == endY && mo <= endMo) {
                out.append((y * 100 + mo, monthAbbrev(monthDate(year: y, month: mo))))
                mo += 1
                if mo > 12 { mo = 1; y += 1 }
            }
            return out
        case .all:
            return []
        }
    }

    // MARK: - the core: metricData (port of _metricData)

    /// Series for the chart (unique people per bucket, recent window vs the preceding one) PLUS the
    /// underlying events so a tap can show *who*. `datesOf` yields the dates a member is counted on.
    public static func metricData(
        _ rows: [Member],
        datesOf: (Member) -> [Date],
        period: KpiPeriod,
        customRange: (start: Date, end: Date)? = nil,
        now: Date = Date()
    ) -> (series: KpiSeries, events: [KpiEvent]) {
        let today = now
        // (member, date) pairs up front so 'All' can choose its bucket granularity from the span.
        var pairs: [(Member, Date)] = []
        for m in rows {
            for dt in datesOf(m) { pairs.append((m, dt)) }
        }

        var allByYear = false
        if period == .all, let earliest = pairs.map({ $0.1 }).min() {
            let e = ymd(earliest), t = ymd(today)
            let months = (t.y - e.y) * 12 + (t.m - e.m)
            allByYear = months > 36
        }

        var sets: [Int: Set<String>] = [:]
        var raw: [(Member, Date, Int)] = []
        for (m, dt) in pairs {
            let id = m.id
            let key = bucketKey(dt, period, allByYear: allByYear)
            sets[key, default: []].insert(id)
            raw.append((m, dt, key))
        }

        var cur: [(key: Int, label: String)]
        var prev: [(key: Int, label: String)]
        if period == .all {
            if raw.isEmpty { return (KpiSeries(), []) }
            let earliest = raw.map { $0.1 }.min()!
            cur = []
            let e = ymd(earliest), t = ymd(today)
            if allByYear {
                var y = e.y
                while y <= t.y { cur.append((y, "\(y)")); y += 1 }
            } else {
                var y = e.y, mo = e.m
                while y < t.y || (y == t.y && mo <= t.m) {
                    let lbl = (y == t.y) ? monthAbbrev(monthDate(year: y, month: mo))
                                         : monthAbbrevYear(monthDate(year: y, month: mo))
                    cur.append((y * 100 + mo, lbl))
                    mo += 1
                    if mo > 12 { mo = 1; y += 1 }
                }
            }
            prev = []
        } else {
            cur = windowBuckets(period, today: today, shift: 0, custom: customRange)
            prev = windowBuckets(period, today: today, shift: 1, custom: customRange)
        }

        var idxOf: [Int: Int] = [:]
        for (i, b) in cur.enumerated() { idxOf[b.key] = i }
        let series = KpiSeries(
            labels: cur.map { $0.label },
            current: cur.map { Double(sets[$0.key]?.count ?? 0) },
            prev: prev.map { Double(sets[$0.key]?.count ?? 0) }
        )
        var events: [KpiEvent] = []
        for r in raw {
            if let i = idxOf[r.2] { events.append(KpiEvent(member: r.0, date: r.1, bucket: i)) }
        }
        return trimEmptyBuckets(series, events)
    }

    /// N9: trim leading AND trailing all-zero buckets so a short/sparse history shows just its data
    /// span (e.g. 5 weeks, or 2 months → 2 points) instead of a long run of padded 0s. Interior gaps
    /// stay; all-zero (no data) → empty series so the chart shows its empty state. Mirrors
    /// `_trimEmptyBuckets` in dashboard_common.dart (the prev overlay is cut to the same indices).
    static func trimEmptyBuckets(_ s: KpiSeries, _ events: [KpiEvent]) -> (series: KpiSeries, events: [KpiEvent]) {
        guard let first = s.current.firstIndex(where: { $0 > 0 }) else { return (KpiSeries(), []) }
        let last = s.current.lastIndex(where: { $0 > 0 })!
        if first == 0 && last == s.current.count - 1 { return (s, events) }
        func cut(_ xs: [Double]) -> [Double] {
            first < xs.count ? Array(xs[first..<min(last + 1, xs.count)]) : []
        }
        let trimmed = KpiSeries(
            labels: Array(s.labels[first...last]),
            current: Array(s.current[first...last]),
            prev: cut(s.prev)
        )
        let evs = events.compactMap { e -> KpiEvent? in
            (e.bucket >= first && e.bucket <= last) ? KpiEvent(member: e.member, date: e.date, bucket: e.bucket - first) : nil
        }
        return (trimmed, evs)
    }

    // MARK: - date extractors (ports of _attendedDates / _firstLessonDate)

    /// Sundays this person was marked present at sacrament (port of `_attendedDates`).
    public static func attendedDates(_ m: Member) -> [Date] {
        guard let sac = m.details?.sacrament else { return [] }
        return sac.compactMap { $0.attended == true ? MemberDate.parse($0.date) : nil }
    }

    /// The single date this person started being taught (port of `_firstLessonDate`).
    public static func firstLessonDate(_ m: Member) -> [Date] {
        guard let d = MemberDate.parse(m.details?.firstLesson) else { return [] }
        return [d]
    }

    // MARK: - sacrament attendance health (#1e / #10b) — ports of web kpis.ts sacramentWindow/attendanceBucket

    /// Semantic attendance level over the recent window. The UI maps level→theme color (never raw color).
    public enum AttendanceLevel: String, Sendable { case great, fair, poor, none, unknown }

    /// Recent sacrament-attendance bucket: raw counts + a semantic level + a short "a/t" label.
    public struct AttendanceBucket: Sendable {
        public let level: AttendanceLevel
        public let attended: Int
        public let total: Int
        public let bold: Bool   // only true for `.none` (0 of window) — the strongest signal
        public let label: String
        public init(level: AttendanceLevel, attended: Int, total: Int, bold: Bool, label: String) {
            self.level = level; self.attended = attended; self.total = total; self.bold = bold; self.label = label
        }
    }

    public static let sacramentWindowWeeks = 8

    /// Most-recent up-to-`weeks` weekly sacrament records → (attended, total). Sorted newest-first when
    /// dates are present (LCR/Member Tools store either order), else trusts the stored order. Entries
    /// without `attended == true` count as missed. nil when there's no attendance list at all. Mirrors
    /// the web `sacramentWindow`.
    public static func sacramentWindow(
        _ list: [MemberDetails.SacramentEntry]?,
        weeks: Int = Kpis.sacramentWindowWeeks
    ) -> (attended: Int, total: Int)? {
        guard let list, !list.isEmpty else { return nil }
        let withDates = list.map { (s: $0, dt: MemberDate.parse($0.date)) }
        let anyDates = withDates.contains { $0.dt != nil }
        let ordered = anyDates
            ? withDates.sorted { ($0.dt ?? .distantPast) > ($1.dt ?? .distantPast) } // newest first; undated sink
            : withDates
        let win = ordered.prefix(max(1, weeks))
        let attended = win.filter { $0.s.attended == true }.count
        return (attended, win.count)
    }

    /// Bucket a member's recent sacrament attendance (8/7 → great, 4–6 → fair, 1–3 → poor, 0 → none+bold;
    /// no data → unknown). Pass the `sacramentWindow(...)` result (or nil). Mirrors `attendanceBucket`.
    public static func attendanceBucket(_ win: (attended: Int, total: Int)?) -> AttendanceBucket {
        guard let win, win.total > 0 else {
            return AttendanceBucket(level: .unknown, attended: 0, total: 0, bold: false, label: "—")
        }
        let a = win.attended
        let level: AttendanceLevel = a >= 7 ? .great : a >= 4 ? .fair : a >= 1 ? .poor : .none
        return AttendanceBucket(level: level, attended: a, total: win.total,
                                bold: level == .none, label: "\(a)/\(win.total)")
    }

    /// Convenience: a member's attendance bucket straight from `details.sacrament`. Mirrors `memberAttendance`.
    public static func memberAttendance(_ m: Member) -> AttendanceBucket {
        attendanceBucket(sacramentWindow(m.details?.sacrament))
    }

    /// Count of lessons (across all people) where a member was present for ≥1 principle.
    /// Port of `_lessonsWithMember`.
    public static func lessonsWithMember(_ rows: [Member]) -> Int {
        var c = 0
        for m in rows {
            for l in m.details?.lessons ?? [] {
                if (l.principles ?? []).contains(where: { $0.memberPresent == true }) { c += 1 }
            }
        }
        return c
    }

    /// Members who had ≥1 member-present lesson, with that count, ranked desc. Port of
    /// `_membersWithMemberLessons`.
    public static func membersWithMemberLessons(_ rows: [Member]) -> [(member: Member, count: Int)] {
        var out: [(Member, Int)] = []
        for m in rows {
            var c = 0
            for l in m.details?.lessons ?? [] {
                if (l.principles ?? []).contains(where: { $0.memberPresent == true }) { c += 1 }
            }
            if c > 0 { out.append((m, c)) }
        }
        out.sort { $0.1 > $1.1 }
        return out
    }

    /// Average Golden Hour completion per unit, ranked high→low. Port of `_unitCompletion`.
    public static func unitCompletion(_ baptized: [Member]) -> [(unit: String, pct: Double, n: Int)] {
        var byUnit: [String: [Member]] = [:]
        for m in baptized { byUnit[m.unitName ?? "—", default: []].append(m) }
        var out = byUnit.map { (unit: $0.key, pct: Milestones.averageCompletion($0.value), n: $0.value.count) }
        out.sort { $0.pct > $1.pct }
        return out
    }

    // MARK: - #1/#2 baptisms by month (port of _baptismsByMonth)

    /// Baptized-convert cohort counted by baptism MONTH over `window`, with the best month named.
    /// "Baptised and confirmed" = the convert cohort, counted by baptism date (confirmation follows).
    public static func baptismsByMonth(_ baptized: [Member], window: BaptismWindow, now: Date = Date()) -> BaptismsByMonth {
        let today = now
        let t = ymd(today)
        let start: Date?
        switch window {
        case .ytd: start = monthDate(year: t.y, month: 1)
        case .m12: start = monthDate(year: t.y, month: t.m - 11)
        case .m24: start = monthDate(year: t.y, month: t.m - 23)
        case .all: start = nil
        }
        var pairs: [(Member, Date)] = []
        for m in baptized {
            guard let dt = MemberDate.parse(m.baptismDate) else { continue }
            if dt > today { continue }                 // no real / future baptism date → skip
            if let s = start, dt < s { continue }
            pairs.append((m, dt))
        }
        let rangeStart: Date
        if let s = start {
            rangeStart = s
        } else if let earliest = pairs.map({ $0.1 }).min() {
            let e = ymd(earliest); rangeStart = monthDate(year: e.y, month: e.m)
        } else {
            rangeStart = monthDate(year: t.y, month: t.m)
        }
        let rs = ymd(rangeStart)
        var labels: [String] = []
        var keys: [Int] = []
        var y = rs.y, mo = rs.m
        while y < t.y || (y == t.y && mo <= t.m) {
            keys.append(y * 100 + mo)
            let d = monthDate(year: y, month: mo)
            labels.append(y == t.y ? monthAbbrev(d) : monthAbbrevYear(d))
            mo += 1
            if mo > 12 { mo = 1; y += 1 }
        }
        var idxOf: [Int: Int] = [:]
        for (i, k) in keys.enumerated() { idxOf[k] = i }
        var counts = [Double](repeating: 0, count: keys.count)
        var events: [KpiEvent] = []
        for (m, dt) in pairs {
            let c = ymd(dt)
            if let i = idxOf[c.y * 100 + c.m] {
                counts[i] += 1                          // a convert is baptized once → counted once
                events.append(KpiEvent(member: m, date: dt, bucket: i))
            }
        }
        var bi = -1
        var bc = 0.0
        for i in counts.indices where counts[i] > bc { bc = counts[i]; bi = i }
        let bestLabel: String? = bi >= 0 ? fullMonth(monthDate(year: keys[bi] / 100, month: keys[bi] % 100)) : nil
        let total = Int(counts.reduce(0, +))
        // N9: trim leading & trailing empty months — show just the data span, not padded 0s. (Total &
        // best span the full in-window range, but trimmed buckets are all 0, so they're unchanged.)
        guard let first = counts.firstIndex(where: { $0 > 0 }) else {
            return BaptismsByMonth(labels: [], counts: [], events: [], bestLabel: nil, bestCount: 0, total: 0)
        }
        let last = counts.lastIndex(where: { $0 > 0 })!
        let evs = events.compactMap { e -> KpiEvent? in
            (e.bucket >= first && e.bucket <= last) ? KpiEvent(member: e.member, date: e.date, bucket: e.bucket - first) : nil
        }
        return BaptismsByMonth(labels: Array(labels[first...last]), counts: Array(counts[first...last]), events: evs,
                               bestLabel: bestLabel, bestCount: Int(bc), total: total)
    }

    // MARK: - label formatters (match Dart's DateFormat usage)

    private static func mdLabel(_ d: Date) -> String {       // 'M/d'
        let c = ymd(d)
        return "\(c.m)/\(c.d)"
    }
    private static let monthNames = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                                     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    private static func monthAbbrev(_ d: Date) -> String {   // 'MMM'
        let m = cal.component(.month, from: d)
        return (m >= 1 && m <= 12) ? monthNames[m - 1] : ""
    }
    private static func monthAbbrevYear(_ d: Date) -> String { // "MMM ''yy"
        let c = ymd(d)
        let yy = String(format: "%02d", c.y % 100)
        return "\(monthAbbrev(d)) '\(yy)"
    }
    private static let fullMonthNames = ["January", "February", "March", "April", "May", "June",
                                         "July", "August", "September", "October", "November", "December"]
    private static func fullMonth(_ d: Date) -> String {       // "MMMM yyyy" → "March 2026" (best month)
        let c = ymd(d)
        return (c.m >= 1 && c.m <= 12) ? "\(fullMonthNames[c.m - 1]) \(c.y)" : "\(c.y)"
    }
}
