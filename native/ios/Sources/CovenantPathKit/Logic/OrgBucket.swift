import Foundation

/// Convert-responsibility hand-off (the stake's #23 policy), ported from `golden_hour.dart`. The
/// first year after baptism the missionaries + ward mission leader (WML) watch over a new member;
/// after a year it moves to the Elders Quorum (men) / Relief Society (women). ONE source of org
/// ownership for the filters + chips.
public enum OrgBucket: String, CaseIterable, Identifiable, Sendable {
    case wml, eq, rs
    public var id: String { rawValue }
}

/// Label + short tag + SF Symbol + identity hex for an org bucket. Colors deliberately avoid the
/// status palette: teal (WML), blue (EQ), rose (RS) — identical hexes to the Flutter `orgInfo`.
public struct OrgInfo: Sendable {
    public let label: String
    public let short: String
    public let symbol: String
    public let hex: UInt32
}

public enum Org {

    public static func info(_ b: OrgBucket) -> OrgInfo {
        switch b {
        case .wml: return OrgInfo(label: "Missionaries / WML", short: "WML",
                                  symbol: "hands.sparkles", hex: 0x00897B)   // teal
        case .eq:  return OrgInfo(label: "Elders Quorum", short: "EQ",
                                  symbol: "person.3", hex: 0x1565C0)         // blue
        case .rs:  return OrgInfo(label: "Relief Society", short: "RS",
                                  symbol: "heart.circle", hex: 0xAD1457)     // rose
        }
    }

    /// Which org currently owns this convert's integration, or nil when there's no baptism date to
    /// reckon from. `< 12 months` → WML; `≥ 12 months` → EQ (men) / RS (women). The month count uses
    /// the same `days / 30.44` (floored) approximation as Flutter so the boundary matches exactly.
    public static func responsible(for m: Member) -> OrgBucket? {
        guard let b = MemberDate.parse(m.baptismDate) else { return nil }
        let days = Calendar.current.dateComponents([.day], from: b, to: Date()).day ?? 0
        let months = Int(floor(Double(days) / 30.44))
        if months < 12 { return .wml }
        return m.isMale ? .eq : .rs
    }

    /// One-line explanation of when converts are this org's responsibility (shown under the filter).
    public static func responsibilityNote(_ b: OrgBucket) -> String {
        switch b {
        case .wml:
            return "First year after baptism: the full-time missionaries and the ward mission "
                 + "leader watch over each new member's progress."
        case .eq:
            return "After the first year: the elders quorum presidency watches over each brother's "
                 + "continued integration."
        case .rs:
            return "After the first year: the Relief Society presidency watches over each sister's "
                 + "continued integration."
        }
    }

    /// Responsibility chip data for a row: label + symbol + hex (Unassigned when no baptism date).
    public static func responsibleParty(_ m: Member) -> (label: String, symbol: String, hex: UInt32?) {
        guard let org = responsible(for: m) else {
            return ("Unassigned", "questionmark.circle", nil)  // nil hex → grey in the view
        }
        let i = info(org)
        return (i.label, i.symbol, i.hex)
    }
}

// MARK: - elapsed-time helper (monthsDaysAgo)

public enum Elapsed {
    /// Compact elapsed time since a past date, e.g. "2 months 3 days" (or "3 days"). Empty for a
    /// future/unknown date. Faithful port of `monthsDaysAgo` (month/day borrow logic included).
    public static func monthsDaysAgo(_ d: Date?) -> String {
        guard let d else { return "" }
        let cal = Calendar.current
        let now = Date()
        if d > now { return "" }

        let nowC = cal.dateComponents([.year, .month, .day], from: now)
        let dC = cal.dateComponents([.year, .month, .day], from: d)
        guard let ny = nowC.year, let nm = nowC.month, let nd = nowC.day,
              let dy = dC.year, let dm = dC.month, let dd = dC.day else { return "" }

        var months = (ny - dy) * 12 + nm - dm
        var days: Int
        if nd >= dd {
            days = nd - dd
        } else {
            months -= 1
            // days in the previous month relative to `now` (day 0 of this month = last day of prev).
            let daysInPrevMonth = daysInMonthBefore(year: ny, month: nm)
            days = daysInPrevMonth - dd + nd
        }
        if months < 0 { return "" }

        var parts: [String] = []
        if months > 0 { parts.append("\(months) month\(months == 1 ? "" : "s")") }
        if days > 0 || months == 0 { parts.append("\(days) day\(days == 1 ? "" : "s")") }
        return parts.joined(separator: " ")
    }

    /// Number of days in the month immediately before (year, month) — mirrors Dart's
    /// `DateTime(now.year, now.month, 0).day`.
    private static func daysInMonthBefore(year: Int, month: Int) -> Int {
        var comps = DateComponents(); comps.year = year; comps.month = month; comps.day = 0
        let cal = Calendar.current
        if let d = cal.date(from: comps) {
            return cal.component(.day, from: d)
        }
        return 30
    }
}
