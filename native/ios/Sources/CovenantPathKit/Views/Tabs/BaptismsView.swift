#if canImport(UIKit)
import SwiftUI

/// Investigators with a *planned* baptism date (`baptism_goal_date`), as a date timeline: an overdue
/// ("date passed") block first, then a "Scheduled" block, each grouped by date. Faithful port of the
/// combined-timeline path of `_OnDateView` / `_Timeline` / `_DateSection` / `_DateRow`.
struct BaptismsView: View {
    let rows: [Member]
    let missionariesByUnit: [String: [Missionary]]

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
    private var overdue: [Dated] { items.filter { $0.date < today } }
    private var upcoming: [Dated] { items.filter { $0.date >= today } }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 8) {
                SectionHeader(title: "Prospective Baptisms", count: items.count, accent: DashboardTab.baptisms.accent)

                if items.isEmpty {
                    EmptyHint("No prospective baptisms with a planned date.")
                } else {
                    if !overdue.isEmpty {
                        dateSection(title: "Needs attention — date passed",
                                    symbol: "exclamationmark.triangle.fill",
                                    color: Color(hex: 0xEF6C00), items: overdue, overdue: true)
                    }
                    if !upcoming.isEmpty {
                        dateSection(title: "Scheduled",
                                    symbol: "calendar.badge.checkmark",
                                    color: DashboardTab.baptisms.accent, items: upcoming, overdue: false)
                    }
                }
            }
            .padding(16)
            .frame(maxWidth: 640)
            .frame(maxWidth: .infinity)
        }
    }

    /// One block (overdue or scheduled): a date-rail of rows grouped by date.
    private func dateSection(title: String, symbol: String, color: Color,
                             items: [Dated], overdue: Bool) -> some View {
        let groups = Dictionary(grouping: items, by: \.date)
        let dates = groups.keys.sorted()  // soonest first (overdue: oldest-passed first)
        return SectionCard(title: title, systemImage: symbol, iconColor: color) {
            VStack(alignment: .leading, spacing: 0) {
                ForEach(Array(dates.enumerated()), id: \.element) { idx, day in
                    if idx > 0 { Divider().padding(.vertical, 9) }
                    DateRailRow(date: day, people: groups[day] ?? [], today: today,
                                overdue: overdue, accent: color, missionariesByUnit: missionariesByUnit)
                }
            }
        }
    }

    /// One date in the rail: a month/day block on the left, the people planned for that day on the
    /// right (each a NavigationLink to detail). Mirrors `_DateRow`.
    private struct DateRailRow: View {
        let date: Date
        let people: [Dated]
        let today: Date
        let overdue: Bool
        let accent: Color
        let missionariesByUnit: [String: [Missionary]]

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

        var body: some View {
            HStack(alignment: .top, spacing: 12) {
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

                VStack(alignment: .leading, spacing: 4) {
                    Text(relative)
                        .font(.system(size: 11, weight: .semibold))
                        .foregroundStyle(overdue ? accent : .secondary)
                    ForEach(people) { p in
                        NavigationLink(value: p.member) {
                            HStack(spacing: 10) {
                                PhotoAvatar(name: p.member.name, photoURL: p.member.photoURL, size: 36)
                                VStack(alignment: .leading, spacing: 1) {
                                    Text(p.member.displayName).fontWeight(.semibold)
                                    Text(p.member.unitName ?? "")
                                        .font(.caption).foregroundStyle(.secondary)
                                }
                                Spacer()
                                Image(systemName: "chevron.right").font(.caption).foregroundStyle(.tertiary)
                            }
                            .padding(.vertical, 4)
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                    }
                }
            }
        }
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
#endif
