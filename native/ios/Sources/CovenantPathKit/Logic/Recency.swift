import Foundation

/// The Golden Hour recency window (Week / Month / Year / All) applied to New Members by baptism date.
/// Day thresholds match `_within` in golden_hour_view.dart exactly (≤7 / ≤31 / ≤366).
public enum Recency: String, CaseIterable, Identifiable, Sendable {
    case week, month, year, all
    public var id: String { rawValue }

    public var label: String {
        switch self {
        case .week: return "Week"
        case .month: return "Month"
        case .year: return "Year"
        case .all: return "All"
        }
    }

    /// Inclusive day count for the window; nil for `.all`.
    public var days: Int? {
        switch self {
        case .week: return 7
        case .month: return 31
        case .year: return 366
        case .all: return nil
        }
    }

    /// Whether a member's baptism date falls inside this window. `.all` always passes; a member with
    /// no parseable baptism date fails any bounded window (matches Flutter).
    public func contains(_ m: Member) -> Bool {
        guard let days else { return true } // .all
        guard let b = MemberDate.parse(m.baptismDate) else { return false }
        let elapsed = MemberDate.cal.dateComponents([.day], from: b, to: Date()).day ?? Int.max
        return elapsed <= days
    }
}

/// Initials for an avatar fallback (mirrors `initialsOf`): first letter of first + last token,
/// commas stripped, uppercased; "?" when empty.
public enum Initials {
    public static func of(_ name: String?) -> String {
        let cleaned = (name ?? "").replacingOccurrences(of: ",", with: "")
            .trimmingCharacters(in: .whitespaces)
        let parts = cleaned.split(whereSeparator: { $0.isWhitespace })
        guard let first = parts.first, let firstChar = first.first else { return "?" }
        if parts.count == 1 { return String(firstChar).uppercased() }
        let last = parts[parts.count - 1]
        let lastChar = last.first.map(String.init) ?? ""
        return (String(firstChar) + lastChar).uppercased()
    }
}
