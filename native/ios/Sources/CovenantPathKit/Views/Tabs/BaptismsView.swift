#if canImport(UIKit)
import SwiftUI

/// Baptisms tab — a CARD PER PERSON (item 1). Each investigator with a planned (future or overdue)
/// baptism date gets their OWN card showing: the planned date + countdown, their unit, full leader
/// notes, their Golden Hour chips + next steps, and the assigned (full-time) missionaries for their
/// unit. Overdue dates (already passed) surface first in a "needs attention" section; genuinely
/// upcoming dates follow. A SECOND section lists the assigned missionaries per unit (item 3/4).
///
/// Faithful port of web `apps/web/src/pages/tabs/BaptismsTab.tsx` (the React rework of the former
/// combined-timeline baptisms_view). A Unit/Date layout toggle is kept for leaders who prefer the
/// unit-grouped layout.
struct BaptismsView: View {
    let rows: [Member]
    let missionariesByUnit: [String: [Missionary]]

    /// Header toggle: card-per-person by date (false) vs per-unit grouping (true). Port of `_byUnit`.
    @State private var byUnit = false

    private struct Dated: Identifiable {
        let member: Member
        let date: Date
        var id: String { member.id }
    }

    /// All investigators with a parseable goal date, normalized to day granularity, sorted soonest-first.
    private var items: [Dated] {
        rows.compactMap { m -> Dated? in
            guard m.isInvestigator, let d = MemberDate.parse(m.baptismGoalDate) else { return nil }
            return Dated(member: m, date: Calendar.current.startOfDay(for: d))
        }
        .sorted { $0.date < $1.date }
    }

    private var today: Date { Calendar.current.startOfDay(for: Date()) }

    /// Every stake unit that has missionaries synced — the full per-unit breakdown for the section
    /// below (item 4); independent of who's in the baptism list, so it's a complete roster.
    private var unitsWithMissionaries: [String] {
        missionariesByUnit
            .filter { !$0.key.trimmingCharacters(in: .whitespaces).isEmpty && !$0.value.isEmpty }
            .keys.sorted()
    }

    var body: some View {
        // Compute the parsed/sorted list ONCE per render.
        let items = self.items
        let units = unitsWithMissionaries
        return ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                HStack {
                    SectionHeader(title: "Upcoming Baptisms", count: items.count,
                                  accent: DashboardTab.baptisms.accent)
                    Picker("Layout", selection: $byUnit) {
                        Label("Unit", systemImage: "person.3").tag(true)
                        Label("Date", systemImage: "calendar").tag(false)
                    }
                    .pickerStyle(.segmented)
                    .frame(width: 160)
                }

                if items.isEmpty {
                    EmptyHint("No baptisms scheduled yet.")
                } else if byUnit {
                    perUnit(items)
                } else {
                    personCardSections(items)
                }

                // SECOND section (item 3/4): assigned/full-time missionaries — a full per-unit breakdown.
                if !units.isEmpty {
                    missionariesByUnitSection(units)
                }
            }
            .padding(16)
            .frame(maxWidth: 760)
            .frame(maxWidth: .infinity)
        }
    }

    // MARK: - card-per-person sections (overdue then scheduled)

    @ViewBuilder
    private func personCardSections(_ items: [Dated]) -> some View {
        let overdue = items.filter { $0.date < today }
        let upcoming = items.filter { $0.date >= today }
        VStack(alignment: .leading, spacing: 18) {
            if !overdue.isEmpty {
                personCardGroup(title: "Needs attention — date has passed",
                                symbol: "exclamationmark.triangle.fill",
                                color: Color(hex: 0xEF6C00), items: overdue, overdue: true)
            }
            if !upcoming.isEmpty {
                personCardGroup(title: "Scheduled", symbol: "calendar.badge.checkmark",
                                color: DashboardTab.baptisms.accent, items: upcoming, overdue: false)
            }
        }
    }

    private func personCardGroup(title: String, symbol: String, color: Color,
                                 items: [Dated], overdue: Bool) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 6) {
                Image(systemName: symbol).font(.system(size: 14)).foregroundStyle(color)
                Text(title).font(.subheadline.weight(.semibold)).foregroundStyle(color)
                CountBadge(items.count)
                Spacer(minLength: 0)
            }
            VStack(spacing: 12) {
                ForEach(items) { it in
                    BaptismPersonCard(member: it.member, date: it.date, today: today,
                                      overdue: overdue, missionaries: missionariesByUnit[it.member.unitName ?? ""] ?? [])
                }
            }
        }
    }

    // MARK: - per-unit grouping (toggle)

    private func perUnit(_ items: [Dated]) -> some View {
        let byUnitMap = Dictionary(grouping: items) { $0.member.unitName ?? "—" }
        let units = byUnitMap.keys.sorted()
        return VStack(spacing: 12) {
            ForEach(units, id: \.self) { u in
                SectionCard(title: u, systemImage: "person.3",
                            trailing: AnyView(CountBadge((byUnitMap[u] ?? []).count))) {
                    VStack(alignment: .leading, spacing: 12) {
                        if let miss = missionariesByUnit[u], !miss.isEmpty {
                            MissionaryStrip(missionaries: miss)
                            Divider()
                        }
                        ForEach(byUnitMap[u] ?? []) { it in
                            BaptismPersonCard(member: it.member, date: it.date, today: today,
                                              overdue: it.date < today,
                                              missionaries: missionariesByUnit[u] ?? [],
                                              nested: true)
                        }
                    }
                }
            }
        }
    }

    // MARK: - Missionaries by Unit (item 4)

    private func missionariesByUnitSection(_ units: [String]) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            SectionHeader(title: "Missionaries by Unit", count: units.count,
                          accent: DashboardTab.baptisms.accent)
            ForEach(units, id: \.self) { u in
                MissionariesSection(unitName: u, title: u,
                                    missionaries: missionariesByUnit[u] ?? [])
            }
        }
    }
}

// MARK: - one card for one person being taught

/// ONE card for ONE investigator: date badge + countdown, unit, Golden Hour chips + next steps, full
/// leader note, and the assigned missionaries who teach them (their unit's full-time missionaries).
/// Mirrors web `BaptismPersonCard`.
struct BaptismPersonCard: View {
    @Environment(DashboardStore.self) private var store: DashboardStore?
    let member: Member
    let date: Date
    let today: Date
    let overdue: Bool
    let missionaries: [Missionary]
    /// When this card sits INSIDE a unit SectionCard (the per-unit layout), use a flat tinted fill
    /// instead of a glass surface so we never nest glass inside glass (per the design-system rule).
    var nested = false

    private var accent: Color { overdue ? Color(hex: 0xEF6C00) : DashboardTab.baptisms.accent }

    private var relative: String {
        let days = Calendar.current.dateComponents([.day], from: today, to: date).day ?? 0
        if overdue {
            let n = -days
            return "\(n) day\(n == 1 ? "" : "s") ago"
        }
        if days == 0 { return "Today" }
        if days == 1 { return "Tomorrow" }
        return "in \(days) days"
    }

    private var note: NoteSummary? {
        guard let uuid = member.personUUID, !uuid.isEmpty else { return nil }
        return store?.notes[uuid]
    }

    private var steps: [Milestone] { Milestones.nextSteps(member) }

    var body: some View {
        // A plain glass card (no SectionCard header — this card carries its own person header).
        VStack(alignment: .leading, spacing: 10) {
            // Header: tappable avatar + name + unit (to detail), date badge on the right.
            HStack(alignment: .top, spacing: 12) {
                NavigationLink(value: member) {
                    HStack(spacing: 12) {
                        PhotoAvatar(name: member.name, photoURL: member.photoURL, size: 44)
                        VStack(alignment: .leading, spacing: 1) {
                            Text(member.displayName).fontWeight(.semibold)
                            if let u = member.unitName, !u.isEmpty {
                                Text(u).font(.caption).foregroundStyle(.secondary)
                            }
                        }
                    }
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                Spacer(minLength: 0)
                dateBadge
            }

            Text("Planned baptism · \(relative)")
                .font(.caption.weight(.semibold)).foregroundStyle(accent)

            // Golden Hour chips — quick covenant-path glance + suggested next step.
            GoldenHourChips(member: member, size: 22, highlightNext: true)

            // Next steps (the not-yet-done Golden Hour milestones for this person).
            if !steps.isEmpty {
                VStack(alignment: .leading, spacing: 4) {
                    Text("NEXT STEPS")
                        .font(.caption2.weight(.bold)).foregroundStyle(.secondary).kerning(0.6)
                    FlowLayout(spacing: 6) {
                        ForEach(steps) { ms in
                            HStack(spacing: 4) {
                                Image(systemName: "circle").font(.caption2)
                                    .foregroundStyle(Color(hex: ms.style.hex))
                                Text(ms.label).font(.caption)
                            }
                            .padding(.horizontal, 8).padding(.vertical, 4)
                            .background(Color(.tertiarySystemFill), in: Capsule())
                        }
                    }
                }
            }

            // Full leader note for this person.
            if let note {
                HStack(alignment: .top, spacing: 4) {
                    Image(systemName: "note.text").font(.caption2).foregroundStyle(Color.accentColor)
                    Text(note.latest).font(.caption).italic().foregroundStyle(.secondary)
                    if note.count > 1 {
                        Text("+\(note.count - 1)").font(.caption).foregroundStyle(.secondary)
                    }
                }
            }

            // Missionary info: who teaches them (their unit's assigned missionaries).
            Divider()
            Text("MISSIONARIES")
                .font(.caption2.weight(.bold)).foregroundStyle(.secondary).kerning(0.6)
            if missionaries.isEmpty {
                Text("No assigned missionaries on record for this ward.")
                    .font(.caption).foregroundStyle(.secondary)
            } else {
                MissionaryStrip(missionaries: missionaries)
            }
        }
        .padding(nested ? 12 : 18)
        .frame(maxWidth: .infinity, alignment: .leading)
        .modifier(CardSurface(nested: nested))
    }

    private var dateBadge: some View {
        VStack(spacing: 0) {
            Text(date.formatted(.dateTime.month(.abbreviated)).uppercased())
                .font(.system(size: 11, weight: .bold)).foregroundStyle(accent)
            Text(date.formatted(.dateTime.day()))
                .font(.system(size: 22, weight: .bold)).foregroundStyle(accent)
            Text(date.formatted(.dateTime.weekday(.abbreviated)))
                .font(.system(size: 10)).foregroundStyle(.secondary)
        }
        .frame(width: 54)
        .padding(.vertical, 6)
        .background(accent.opacity(0.10), in: RoundedRectangle(cornerRadius: 10))
    }
}

// MARK: - small shared header / hints

/// A section header with an accent bar, title, and count (mirrors `_SectionTitle`'s left side).
struct SectionHeader: View {
    let title: String
    let count: Int
    var accent: Color = .accentColor
    var body: some View {
        HStack(spacing: 8) {
            RoundedRectangle(cornerRadius: 2).fill(accent).frame(width: 4, height: 22)
            Text(title).font(.title3.bold())
            CountBadge(count)
            Spacer()
        }
    }
}

struct EmptyHint: View {
    let text: String
    init(_ text: String) { self.text = text }
    var body: some View {
        Text(text)
            .foregroundStyle(.secondary)
            .frame(maxWidth: .infinity)
            .padding(32)
    }
}

/// A card surface that's a glass card at top level, but a flat tinted fill when nested inside another
/// glass card (so we never stack glass on glass — per the design-system rule in Glass.swift).
struct CardSurface: ViewModifier {
    let nested: Bool
    func body(content: Content) -> some View {
        if nested {
            content.background(Color(.secondarySystemBackground),
                               in: RoundedRectangle(cornerRadius: 14, style: .continuous))
        } else {
            content.cpGlassCard()
        }
    }
}

/// The full-time missionaries assigned to a unit (port of `_MissionaryStrip`): name chips; tapping a
/// chip reveals phone/email (a Menu with call/email actions — the native analog of the tap tooltip).
struct MissionaryStrip: View {
    let missionaries: [Missionary]
    var body: some View {
        HStack(alignment: .top, spacing: 6) {
            Image(systemName: "person.2").font(.caption).foregroundStyle(.tint)
            FlowLayout(spacing: 6) {
                ForEach(Array(missionaries.enumerated()), id: \.offset) { _, m in
                    chip(m)
                }
            }
        }
    }

    @ViewBuilder
    private func chip(_ m: Missionary) -> some View {
        let phone = m.phone ?? ""
        let email = m.email ?? ""
        let label = Text(m.name ?? "")
            .font(.caption).fontWeight(.medium)
            .padding(.horizontal, 9).padding(.vertical, 4)
            .background(Color.accentColor.opacity(0.10), in: Capsule())
            .foregroundStyle(Color.accentColor)
        if phone.isEmpty && email.isEmpty {
            label
        } else {
            Menu {
                if !phone.isEmpty {
                    if let url = URL(string: "tel:\(phone.filter { !$0.isWhitespace })") {
                        Link(destination: url) { Label(phone, systemImage: "phone") }
                    } else { Text(phone) }
                }
                if !email.isEmpty {
                    if let url = URL(string: "mailto:\(email)") {
                        Link(destination: url) { Label(email, systemImage: "envelope") }
                    } else { Text(email) }
                }
            } label: { label }
        }
    }
}

/// A detail-style list of a unit's missionaries with contact lines (used in the per-unit section + the
/// person detail view). Renders a clean empty state when none are synced for the unit. Mirrors web
/// `MissionariesSection` — but takes the missionary list directly (the data already on the stake) so it
/// works both inside the dashboard and on the detail page. `title` defaults to "Full-Time Missionaries".
struct MissionariesSection: View {
    let unitName: String?
    var title: String = "Full-Time Missionaries"
    let missionaries: [Missionary]

    var body: some View {
        SectionCard(title: title, systemImage: "person.2.fill") {
            if missionaries.isEmpty {
                Text("No assigned missionaries on record for "
                     + (unitName.map { "\($0)." } ?? "this unit."))
                    .foregroundStyle(.secondary)
            } else {
                VStack(alignment: .leading, spacing: 8) {
                    ForEach(Array(missionaries.enumerated()), id: \.offset) { _, m in
                        HStack(alignment: .top, spacing: 10) {
                            InitialsAvatar(name: m.name ?? "?", size: 32)
                            VStack(alignment: .leading, spacing: 1) {
                                Text(m.name ?? "—")
                                if let phone = m.phone, !phone.isEmpty {
                                    if let url = URL(string: "tel:\(phone.filter { !$0.isWhitespace })") {
                                        Link(phone, destination: url).font(.caption).foregroundStyle(.secondary)
                                    } else {
                                        Text(phone).font(.caption).foregroundStyle(.secondary)
                                    }
                                }
                                if let email = m.email, !email.isEmpty {
                                    if let url = URL(string: "mailto:\(email)") {
                                        Link(email, destination: url).font(.caption).foregroundStyle(.secondary)
                                    } else {
                                        Text(email).font(.caption).foregroundStyle(.secondary)
                                    }
                                }
                            }
                            Spacer(minLength: 0)
                        }
                    }
                }
            }
        }
    }
}
#endif
