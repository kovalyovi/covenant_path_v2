#if canImport(UIKit)
import SwiftUI

/// A single member row used in lists (Golden Hour, Needs, Being Taught). Mirrors `_MemberRow`:
/// avatar + name (+ age) on top; a date line, the responsible-org chip, and (optionally) the Golden
/// Hour chips beneath; unit shown as right-side metadata. Tapping opens detail (via NavigationLink
/// provided by the caller).
public struct MemberRow: View {
    let member: Member
    var showChips: Bool = false
    var showUnit: Bool = false
    var showResponsible: Bool = false
    /// Which date field to render ("baptism_date" → "Baptized …(tenure)"; otherwise a long date).
    var dateField: DateField = .baptism

    public enum DateField { case baptism, goal }

    public init(member: Member, showChips: Bool = false, showUnit: Bool = false,
                showResponsible: Bool = false, dateField: DateField = .baptism) {
        self.member = member; self.showChips = showChips; self.showUnit = showUnit
        self.showResponsible = showResponsible; self.dateField = dateField
    }

    private var rawDate: String? { dateField == .baptism ? member.baptismDate : member.baptismGoalDate }
    private var date: Date? { MemberDate.parse(rawDate) }
    private var isBaptism: Bool { dateField == .baptism }

    public var body: some View {
        HStack(alignment: .top, spacing: 10) {
            PhotoAvatar(name: member.name, photoURL: member.photoURL, size: 44)
            VStack(alignment: .leading, spacing: 6) {
                HStack(spacing: 6) {
                    Text(member.displayName).fontWeight(.semibold)
                    if let age = Milestones.ageLabel(member) {
                        Text("· \(age)").font(.subheadline).foregroundStyle(.secondary)
                    }
                }
                if let date {
                    Label {
                        Text(dateLine(date)).font(.caption).foregroundStyle(.secondary)
                    } icon: {
                        Image(systemName: isBaptism ? "drop.fill" : "calendar")
                            .font(.caption2)
                            .foregroundStyle(isBaptism ? Color(hex: 0x29B6F6) : .secondary)
                    }
                }
                if showChips || showResponsible {
                    responsibleChip
                }
                if showChips {
                    GoldenHourChips(member: member, size: 22, highlightNext: true)
                        .padding(.top, 2)
                }
            }
            Spacer(minLength: 8)
            if showUnit {
                Text(member.unitName ?? "")
                    .font(.caption).foregroundStyle(.secondary)
                    .multilineTextAlignment(.trailing)
                    .frame(maxWidth: 120, alignment: .trailing)
            } else {
                Image(systemName: "chevron.right").font(.caption).foregroundStyle(.tertiary)
            }
        }
        .padding(.vertical, 6)
        .contentShape(Rectangle())
    }

    private var responsibleChip: some View {
        let r = Org.responsibleParty(member)
        let color = r.hex.map { Color(hex: $0) } ?? .secondary
        return HStack(spacing: 4) {
            Image(systemName: r.symbol).font(.caption2)
            Text(r.label).font(.caption)
        }
        .foregroundStyle(color)
    }

    private func dateLine(_ date: Date) -> String {
        if isBaptism {
            let elapsed = Elapsed.monthsDaysAgo(date)
            let base = date.formatted(.dateTime.month(.wide).day().year())
            return elapsed.isEmpty ? base : "\(base) (\(elapsed))"
        }
        // Long form, e.g. "Tuesday, February 6, 2026" (matches fmtLong).
        return date.formatted(.dateTime.weekday(.wide).month(.wide).day().year())
    }
}
#endif
