#if canImport(UIKit)
import SwiftUI
import Charts

/// KPIs from this stake's covenant-path data, as Swift Charts line cards + an Overview stat grid +
/// a Golden-Hour-by-unit ranked bar list. Faithful port of `kpis_view.dart` (`_KpiView`): the
/// Month/Year/All period with a date-range pill + Compare toggle, the three metric charts
/// (Investigators / New Members at Sacrament, New Friends being taught) overlaying the previous
/// window, and the drill sheets (by unit / by date). Series math is `Kpis` (ported exactly).
struct KPIsView: View {
    let rows: [Member]

    @State private var period: KpiPeriod = .month
    @State private var unit: String?          // nil = whole stake
    @State private var compare = false
    @State private var drill: DrillPayload?
    @State private var ghBreakdown = false
    @State private var lessonsDrill = false

    private var units: [String] {
        Array(Set(rows.compactMap { $0.unitName }.filter { !$0.isEmpty })).sorted()
    }
    private var scoped: [Member] {
        guard let unit else { return rows }
        return rows.filter { $0.unitName == unit }
    }
    private var baptized: [Member] { scoped.filter { !$0.isInvestigator } }
    private var investigators: [Member] { scoped.filter { $0.isInvestigator } }
    private var allUnits: Set<String> { Set(scoped.map { $0.unitName ?? "—" }) }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                header

                let friendsAtSac = Kpis.metricData(investigators, datesOf: Kpis.attendedDates, period: period)
                let newAtSac = Kpis.metricData(baptized, datesOf: Kpis.attendedDates, period: period)
                let newFriends = Kpis.metricData(investigators, datesOf: Kpis.firstLessonDate, period: period)

                // "Baptisms by month" now lives in its own dedicated tab (the last one) — see
                // BaptismsByMonthView.

                MetricChartCard(title: "Investigators at Sacrament", symbol: "person.3",
                                hex: 0xEF6C00, data: friendsAtSac, period: period, compare: compare,
                                suffix: "people being taught who attended sacrament",
                                allUnits: allUnits, onDrill: { drill = $0 })
                MetricChartCard(title: "New Members at Sacrament", symbol: "heart.fill",
                                hex: 0xB5532A, data: newAtSac, period: period, compare: compare,
                                suffix: "baptized members who attended sacrament",
                                allUnits: allUnits, onDrill: { drill = $0 })
                MetricChartCard(title: "New Friends Being Taught", symbol: "books.vertical",
                                hex: 0x00897B, data: newFriends, period: period, compare: compare,
                                suffix: "people who started lessons in the period",
                                allUnits: allUnits, onDrill: { drill = $0 })

                overviewCard

                if unit == nil && units.count > 1 {
                    unitCompletionCard
                }
            }
            .padding(16)
            .frame(maxWidth: 760)
            .frame(maxWidth: .infinity)
        }
        .sheet(item: $drill) { d in
            KpiDrillSheet(title: d.title, events: d.events, allUnits: d.allUnits, bucketLabel: d.bucketLabel)
        }
        .sheet(isPresented: $ghBreakdown) {
            GoldenHourBreakdownSheet(rows: baptized)
        }
        .sheet(isPresented: $lessonsDrill) {
            LessonsDrillSheet(people: Kpis.membersWithMemberLessons(scoped))
        }
    }

    // MARK: - header (period + unit + compare)

    private var header: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .top) {
                BigHeader(title: "KPIs", subtitle: "From this stake's covenant-path data",
                          accent: DashboardTab.kpis.accent)
                if units.count > 1 {
                    Menu {
                        Button("All units") { unit = nil }
                        ForEach(units, id: \.self) { u in Button(u) { unit = u } }
                    } label: {
                        HStack(spacing: 2) {
                            Text(unit ?? "All units").font(.caption)
                            Image(systemName: "chevron.down").font(.caption2)
                        }
                    }
                }
            }
            Picker("Period", selection: $period) {
                ForEach(KpiPeriod.allCases) { p in Text(p.label).tag(p) }
            }
            .pickerStyle(.segmented)

            if let range = periodRangeLabel {
                RangePill(range).frame(maxWidth: .infinity)
            }
            if period != .all {
                Toggle(isOn: $compare) {
                    Label("Compare to previous", systemImage: "arrow.left.arrow.right")
                }
                .toggleStyle(.button)
                .font(.caption)
                .frame(maxWidth: .infinity)
            }
        }
    }

    /// The date range the x-axis spans (port of `_periodRangeLabel`); nil for All.
    private var periodRangeLabel: String? {
        let now = Date()
        switch period {
        case .month:
            let from = Calendar.current.date(byAdding: .day, value: -35, to: now) ?? now
            return "\(from.formatted(.dateTime.month(.abbreviated).day())) – \(now.formatted(.dateTime.month(.abbreviated).day().year()))"
        case .year:
            let from = Calendar.current.date(byAdding: .month, value: -11, to: now) ?? now
            return "\(from.formatted(.dateTime.month(.abbreviated).year())) – \(now.formatted(.dateTime.month(.abbreviated).year()))"
        case .all:
            return nil
        }
    }

    // MARK: - Overview stat grid (port of `_StatGridCard`)

    private var overviewCard: some View {
        let lessonsWithMember = Kpis.lessonsWithMember(scoped)
        let completion = Milestones.averageCompletion(baptized)
        return SectionCard(title: "Overview", systemImage: "square.grid.2x2", iconColor: DashboardTab.kpis.accent) {
            FlowLayout(spacing: 24, lineSpacing: 16) {
                statTile("Being taught now", "\(investigators.count)") {
                    drill = DrillPayload(title: "Being taught now",
                                         events: evs(investigators, \.baptismGoalDate), allUnits: allUnits)
                }
                statTile("Lessons w/ member present", "\(lessonsWithMember)") { lessonsDrill = true }
                statTile("New members tracked", "\(baptized.count)") {
                    drill = DrillPayload(title: "New members tracked",
                                         events: evs(baptized, \.baptismDate), allUnits: allUnits)
                }
                statTile("Golden Hour", "\(Int((completion * 100).rounded()))%") { ghBreakdown = true }
            }
        }
    }

    private func statTile(_ label: String, _ value: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 3) {
                    Text(value).font(.title.bold())
                    Image(systemName: "chevron.right").font(.caption).foregroundStyle(.tertiary)
                }
                Text(label).font(.caption).foregroundStyle(.secondary)
            }
            .frame(width: 150, alignment: .leading)
        }
        .buttonStyle(.plain)
    }

    /// One event per member at "now-bucket 0" (the overview drills don't bucket). Port of `evs`.
    private func evs(_ ms: [Member], _ field: KeyPath<Member, String?>) -> [KpiEvent] {
        ms.map { KpiEvent(member: $0, date: MemberDate.parse($0[keyPath: field]) ?? Date(), bucket: 0) }
    }

    // MARK: - Golden Hour by unit (port of `_UnitCompletionCard`)

    private var unitCompletionCard: some View {
        let ranked = Kpis.unitCompletion(baptized)
        return Group {
            if ranked.count >= 2 {
                SectionCard(title: "Golden Hour by unit", systemImage: "chart.bar.xaxis",
                            iconColor: DashboardTab.kpis.accent) {
                    VStack(spacing: 10) {
                        ForEach(ranked, id: \.unit) { r in
                            Button {
                                unit = r.unit
                            } label: {
                                HStack {
                                    Text(r.unit).font(.subheadline).lineLimit(1)
                                    Spacer()
                                    ProgressView(value: r.pct).frame(width: 120)
                                    Text("\(Int((r.pct * 100).rounded()))% · \(r.n)")
                                        .font(.caption).foregroundStyle(.secondary)
                                        .frame(width: 64, alignment: .trailing)
                                }
                            }
                            .buttonStyle(.plain)
                        }
                    }
                }
            }
        }
    }
}

/// A drill payload for the sheet (Identifiable so `.sheet(item:)` works).
struct DrillPayload: Identifiable {
    let title: String
    let events: [KpiEvent]
    let allUnits: Set<String>
    var bucketLabel: String?
    var id: String { title + (bucketLabel ?? "") }
}

/// #1/#2: baptized-convert cohort by baptism month over YTD / 12 mo / 24 mo / All, with the best
/// month named and a by-unit drill. Its own window selector (independent of the page period).
struct BaptismsCard: View {
    let baptized: [Member]
    let allUnits: Set<String>
    let onDrill: (DrillPayload) -> Void

    @State private var window: BaptismWindow = .ytd // default to year-to-date
    private let color = Color(hex: 0x0277BD)

    var body: some View {
        let d = Kpis.baptismsByMonth(baptized, window: window)
        SectionCard(title: "Baptisms by month", systemImage: "drop.fill", iconColor: color) {
            VStack(alignment: .leading, spacing: 14) {
                Picker("Window", selection: $window) {
                    ForEach(BaptismWindow.allCases) { w in Text(w.label).tag(w) }
                }
                .pickerStyle(.segmented)

                HStack(alignment: .top) {
                    statKV("Baptized in window", "\(d.total)")
                    Divider().frame(height: 36)
                    statKV("Best month", d.bestLabel.map { "\($0) · \(d.bestCount)" } ?? "—")
                }

                chart(d)

                HStack {
                    Text("Baptized & confirmed converts, counted by baptism month.")
                        .font(.caption).foregroundStyle(.secondary)
                    Spacer()
                    Button {
                        onDrill(DrillPayload(title: "Baptisms", events: d.events, allUnits: allUnits))
                    } label: { Label("By unit", systemImage: "person.3").font(.caption) }
                }
            }
        }
    }

    private func statKV(_ label: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label).font(.caption).foregroundStyle(.secondary)
            Text(value).font(.headline)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    @ViewBuilder
    private func chart(_ d: BaptismsByMonth) -> some View {
        if d.counts.isEmpty || d.total == 0 {
            Text("No baptisms in this window").foregroundStyle(.secondary)
                .frame(maxWidth: .infinity, minHeight: 150)
        } else {
            let yMax = (d.counts.max() ?? 0) * 1.35 + 1
            let step = max(1, Int((Double(d.counts.count) / 3.0).rounded(.up)))
            let ticks = Array(stride(from: 0, to: d.counts.count, by: step))
            Chart {
                ForEach(Array(d.counts.enumerated()), id: \.offset) { i, v in
                    LineMark(x: .value("i", i), y: .value("count", v))
                        .foregroundStyle(color)
                        .interpolationMethod(.catmullRom)
                    AreaMark(x: .value("i", i), y: .value("count", v))
                        .foregroundStyle(.linearGradient(colors: [color.opacity(0.28), color.opacity(0.02)],
                                                         startPoint: .top, endPoint: .bottom))
                        .interpolationMethod(.catmullRom)
                    PointMark(x: .value("i", i), y: .value("count", v))
                        .foregroundStyle(color)
                        .symbolSize(60)
                        .annotation(position: .top, spacing: 2) {
                            Text("\(Int(v))").font(.system(size: 10, weight: .bold)).foregroundStyle(color)
                        }
                }
            }
            .chartYScale(domain: 0...yMax)
            .chartXAxis {
                AxisMarks(values: ticks) { value in
                    if let i = value.as(Int.self), i >= 0, i < d.labels.count {
                        AxisValueLabel { Text(d.labels[i]).font(.system(size: 10)).foregroundStyle(.secondary) }
                    }
                }
            }
            .chartYAxis(.hidden)
            .frame(height: 170)
            .chartOverlay { proxy in
                GeometryReader { geo in
                    Rectangle().fill(.clear).contentShape(Rectangle())
                        .onTapGesture { location in
                            if let i: Int = proxy.value(atX: location.x - geo[proxy.plotAreaFrame].origin.x) {
                                let clamped = max(0, min(d.counts.count - 1, i))
                                let evs = d.events.filter { $0.bucket == clamped }
                                let label = clamped < d.labels.count ? d.labels[clamped] : nil
                                onDrill(DrillPayload(title: "Baptisms", events: evs, allUnits: allUnits, bucketLabel: label))
                            }
                        }
                }
            }
        }
    }
}

/// One metric line chart card: big prior/latest stats + a Swift Charts line (current vs previous
/// overlay) + a "By unit" drill button + the tap-a-point drill. Port of `_MetricChartCard`/`_Line`.
struct MetricChartCard: View {
    let title: String
    let symbol: String
    let hex: UInt32
    let data: (series: KpiSeries, events: [KpiEvent])
    let period: KpiPeriod
    let compare: Bool
    let suffix: String
    let allUnits: Set<String>
    let onDrill: (DrillPayload) -> Void

    private var color: Color { Color(hex: hex) }
    private var values: [Double] { data.series.current }
    private var last: Double? { values.last }
    private var prior: Double? { values.count >= 2 ? values[values.count - 2] : nil }

    var body: some View {
        SectionCard(title: title, systemImage: symbol, iconColor: color,
                    trailing: deltaBadge) {
            VStack(alignment: .leading, spacing: 12) {
                if let last, let prior {
                    HStack {
                        bigStat(period.compareLabels.prev, prior)
                        Divider().frame(height: 36)
                        bigStat(period.compareLabels.latest, last)
                    }
                }
                chart
                HStack {
                    Text(suffix).font(.caption).foregroundStyle(.secondary)
                    Spacer()
                    Button {
                        onDrill(DrillPayload(title: title, events: data.events, allUnits: allUnits))
                    } label: {
                        Label("By unit", systemImage: "person.3").font(.caption)
                    }
                }
            }
        }
    }

    @ViewBuilder
    private var chart: some View {
        if values.isEmpty {
            Text("No data yet").foregroundStyle(.secondary)
                .frame(maxWidth: .infinity, minHeight: 150)
        } else {
            Chart {
                if compare && !data.series.prev.isEmpty {
                    ForEach(Array(data.series.prev.enumerated()), id: \.offset) { i, v in
                        LineMark(x: .value("i", i), y: .value("prev", v),
                                 series: .value("s", "Previous"))
                            .foregroundStyle(.gray)
                            .lineStyle(StrokeStyle(lineWidth: 2, dash: [5, 4]))
                            .interpolationMethod(.catmullRom)
                    }
                }
                ForEach(Array(values.enumerated()), id: \.offset) { i, v in
                    LineMark(x: .value("i", i), y: .value("count", v),
                             series: .value("s", "Current"))
                        .foregroundStyle(color)
                        .interpolationMethod(.catmullRom)
                    AreaMark(x: .value("i", i), y: .value("count", v))
                        .foregroundStyle(.linearGradient(colors: [color.opacity(0.28), color.opacity(0.02)],
                                                         startPoint: .top, endPoint: .bottom))
                        .interpolationMethod(.catmullRom)
                    PointMark(x: .value("i", i), y: .value("count", v))
                        .foregroundStyle(color)
                        .symbolSize(60)
                        .annotation(position: .top, spacing: 2) {
                            Text(fmt(v)).font(.system(size: 10, weight: .bold)).foregroundStyle(color)
                        }
                }
            }
            .chartYScale(domain: 0...(yMax))
            .chartXAxis {
                AxisMarks(values: xTickIndices) { value in
                    if let i = value.as(Int.self), i >= 0, i < data.series.labels.count {
                        AxisValueLabel { Text(data.series.labels[i]).font(.system(size: 10)).foregroundStyle(.secondary) }
                    }
                }
            }
            .chartYAxis(.hidden)
            .frame(height: 170)
            .chartOverlay { proxy in
                GeometryReader { geo in
                    Rectangle().fill(.clear).contentShape(Rectangle())
                        .onTapGesture { location in
                            if let i: Int = proxy.value(atX: location.x - geo[proxy.plotAreaFrame].origin.x) {
                                let clamped = max(0, min(values.count - 1, i))
                                let evs = data.events.filter { $0.bucket == clamped }
                                let label = clamped < data.series.labels.count ? data.series.labels[clamped] : nil
                                onDrill(DrillPayload(title: title, events: evs, allUnits: allUnits, bucketLabel: label))
                            }
                        }
                }
            }
        }
    }

    private var yMax: Double {
        let peak = (values + (compare ? data.series.prev : [])).max() ?? 0
        return peak * 1.35 + 1
    }
    private var xTickIndices: [Int] {
        let n = data.series.labels.count
        guard n > 0 else { return [] }
        let step = max(1, Int((Double(n) / 3).rounded(.up)))
        var out: [Int] = []
        var i = 0
        while i < n { out.append(i); i += step }
        if out.last != n - 1 { out.append(n - 1) }
        return out
    }

    private var deltaBadge: AnyView? {
        guard let last, let prior else { return nil }
        return AnyView(DeltaBadge(delta: last - prior))
    }

    private func bigStat(_ label: String, _ v: Double) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label).font(.caption).foregroundStyle(.secondary)
            Text(fmt(v)).font(.title.bold())
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func fmt(_ v: Double) -> String {
        v == v.rounded() ? "\(Int(v))" : String(format: "%.1f", v)
    }
}

struct DeltaBadge: View {
    let delta: Double
    var body: some View {
        let up = delta >= 0
        let c = up ? StatusColor.done : Color(hex: 0xD32F2F)
        let v = delta == delta.rounded() ? "\(Int(abs(delta)))" : String(format: "%.1f", abs(delta))
        return Text("\(up ? "+" : "−")\(v)")
            .font(.caption.weight(.semibold))
            .padding(.horizontal, 8).padding(.vertical, 3)
            .background(c.opacity(0.12), in: Capsule())
            .foregroundStyle(c)
    }
}

/// Drill sheet: by-unit (every unit, incl. 0) expandable, or chronological. Port of `_DrillSheet`.
struct KpiDrillSheet: View {
    let title: String
    let events: [KpiEvent]
    let allUnits: Set<String>
    var bucketLabel: String?
    @State private var byUnit = true

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    Picker("View", selection: $byUnit) {
                        Text("By unit").tag(true)
                        Text("By date").tag(false)
                    }
                    .pickerStyle(.segmented)

                    if byUnit { byUnitList } else { chronoList }
                }
                .padding(16)
            }
            .navigationTitle(title + (bucketLabel.map { " · \($0)" } ?? ""))
            .navigationBarTitleDisplayMode(.inline)
            .navigationDestination(for: Member.self) { PersonDetailView(member: $0) }
        }
        .presentationDetents([.medium, .large])
    }

    private func unitName(_ m: Member) -> String { m.unitName ?? "—" }

    private var byUnitList: some View {
        // group events by unit (unique members per unit), include zero-count units
        var byUnit: [String: [String: Member]] = [:]
        for u in allUnits { byUnit[u] = [:] }
        for e in events { byUnit[unitName(e.member), default: [:]][e.member.id] = e.member }
        let units = byUnit.keys.sorted()
        return VStack(spacing: 8) {
            ForEach(units, id: \.self) { u in
                let members = (byUnit[u] ?? [:]).values.sorted { ($0.name ?? "") < ($1.name ?? "") }
                SectionCard(title: u, trailing: AnyView(CountBadge(members.count))) {
                    if members.isEmpty {
                        Text("0").foregroundStyle(.secondary)
                    } else {
                        VStack(spacing: 0) {
                            ForEach(Array(members.enumerated()), id: \.element.id) { i, m in
                                if i > 0 { Divider() }
                                NavigationLink(value: m) { personRow(m) }.buttonStyle(.plain)
                            }
                        }
                    }
                }
            }
        }
    }

    private var chronoList: some View {
        let sorted = events.sorted { $0.date > $1.date }
        return Group {
            if sorted.isEmpty {
                Text("No one in this view.").foregroundStyle(.secondary).padding()
            } else {
                VStack(spacing: 0) {
                    ForEach(sorted) { e in
                        NavigationLink(value: e.member) {
                            HStack(spacing: 10) {
                                PhotoAvatar(name: e.member.name, photoURL: e.member.photoURL, size: 32)
                                VStack(alignment: .leading) {
                                    Text(e.member.displayName)
                                    Text("\(unitName(e.member)) · \(e.date.formatted(.dateTime.weekday(.wide).month(.wide).day().year()))")
                                        .font(.caption).foregroundStyle(.secondary)
                                }
                                Spacer()
                            }
                            .padding(.vertical, 6)
                        }
                        .buttonStyle(.plain)
                        Divider()
                    }
                }
            }
        }
    }

    private func personRow(_ m: Member) -> some View {
        HStack(spacing: 10) {
            PhotoAvatar(name: m.name, photoURL: m.photoURL, size: 32)
            Text(m.displayName)
            Spacer()
            Image(systemName: "chevron.right").font(.caption).foregroundStyle(.tertiary)
        }
        .padding(.vertical, 6)
    }
}

/// Golden Hour by category, eligible-only, each expandable to the missing members. Port of
/// `_showGoldenHourBreakdown`.
struct GoldenHourBreakdownSheet: View {
    let rows: [Member]
    var body: some View {
        NavigationStack {
            List {
                Section {
                    Text("Eligible-only — members who don't qualify (age, sex, tenure) are excluded so the % reflects who actually still needs it.")
                        .font(.caption).foregroundStyle(.secondary)
                }
                ForEach(Milestones.all) { ms in
                    let eligible = rows.filter(ms.eligible)
                    if !eligible.isEmpty {
                        let missing = Milestones.missing(ms, in: rows).sorted { ($0.name ?? "") < ($1.name ?? "") }
                        let done = eligible.count - missing.count
                        let pct = Double(done) / Double(eligible.count)
                        Section {
                            if missing.isEmpty {
                                Text("Everyone eligible has this. 🎉").foregroundStyle(.secondary)
                            } else {
                                ForEach(missing) { m in
                                    NavigationLink(value: m) {
                                        HStack(spacing: 10) {
                                            PhotoAvatar(name: m.name, photoURL: m.photoURL, size: 30)
                                            VStack(alignment: .leading) {
                                                Text(m.displayName)
                                                Text(m.unitName ?? "").font(.caption).foregroundStyle(.secondary)
                                            }
                                        }
                                    }
                                }
                            }
                        } header: {
                            HStack {
                                Text(ms.label)
                                Spacer()
                                Text("\(Int((pct * 100).rounded()))% · \(done)/\(eligible.count)")
                            }
                            .textCase(nil)
                        }
                    }
                }
            }
            .navigationTitle("Golden Hour by category")
            .navigationBarTitleDisplayMode(.inline)
            .navigationDestination(for: Member.self) { PersonDetailView(member: $0) }
        }
        .presentationDetents([.large])
    }
}

/// The members behind "Lessons with a member present", ranked. Port of `_showLessonsDrill`.
struct LessonsDrillSheet: View {
    let people: [(member: Member, count: Int)]
    var body: some View {
        NavigationStack {
            Group {
                if people.isEmpty {
                    Text("No member-present lessons recorded yet.").foregroundStyle(.secondary).padding()
                } else {
                    List {
                        ForEach(people, id: \.member.id) { p in
                            NavigationLink(value: p.member) {
                                HStack(spacing: 10) {
                                    PhotoAvatar(name: p.member.name, photoURL: p.member.photoURL, size: 34)
                                    VStack(alignment: .leading) {
                                        Text(p.member.displayName)
                                        Text(p.member.unitName ?? "").font(.caption).foregroundStyle(.secondary)
                                    }
                                    Spacer()
                                    CountBadge(p.count)
                                }
                            }
                        }
                    }
                    .navigationDestination(for: Member.self) { PersonDetailView(member: $0) }
                }
            }
            .navigationTitle("Lessons with a member present")
            .navigationBarTitleDisplayMode(.inline)
        }
        .presentationDetents([.medium, .large])
    }
}
#endif
