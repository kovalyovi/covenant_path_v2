import Foundation

/// Date parsing that mirrors the Flutter app's `parseMemberDate` / `_dateOf` (golden_hour.dart +
/// dashboard_common.dart). The backend stores dates as free-text strings plus a handful of
/// sentinel values that must be treated as "unknown" (null):
///
///   - ISO: `2026-02-06`            (also accepts a trailing time, like Dart's DateTime.tryParse)
///   - `6 Feb 2026`                  (day month-abbrev year)
///   - `2/6/2026` or `2/6/26`        (US month/day/year)
///   - `N/A`, `needs-profile-api`, `blocked: …`, empty → nil
///
/// All comparisons in the milestone logic are done in the *local* calendar, matching Flutter's
/// `DateTime.now()` (local) usage. We therefore parse into a `Date` and let `Calendar.current`
/// interpret it; date-only strings are pinned to local midnight.
public enum MemberDate {

    static let monthAbbrevs = ["jan", "feb", "mar", "apr", "may", "jun",
                               "jul", "aug", "sep", "oct", "nov", "dec"]

    /// Parse a backend date string to a local `Date`, or `nil` for empty / sentinel / unparseable.
    public static func parse(_ raw: String?) -> Date? {
        guard let raw else { return nil }
        let s = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        if s.isEmpty { return nil }
        let lower = s.lowercased()
        // Sentinels the sync writes when a field can't be resolved. Flutter checks `N/A` and
        // `needs-profile-api`; `blocked:` prefixes are documented in the spec as "treat as null".
        if lower == "n/a" || lower == "needs-profile-api" || lower.hasPrefix("blocked") {
            return nil
        }

        if let iso = parseISO(s) { return iso }
        if let dmy = parseDayMonthYear(s) { return dmy }
        if let mdy = parseSlash(s) { return mdy }
        return nil
    }

    /// Convenience: parse a `JSONValue`/`Any?`-ish string-bearing value (used from Codable models
    /// that store the raw text). Pass the already-extracted string.
    public static func parse(value: String?) -> Date? { parse(value) }

    // MARK: - sub-parsers

    /// ISO-8601 / `yyyy-MM-dd` (optionally with a time component). Mirrors Dart's lenient
    /// `DateTime.tryParse`, which accepts both `2026-02-06` and `2026-02-06T12:00:00Z`.
    private static func parseISO(_ s: String) -> Date? {
        // Pure date `yyyy-MM-dd` → local midnight (so "days since" math matches Flutter).
        if let m = firstMatch(#"^(\d{4})-(\d{1,2})-(\d{1,2})$"#, in: s),
           let y = Int(m[1]), let mo = Int(m[2]), let d = Int(m[3]) {
            return localDate(year: y, month: mo, day: d)
        }
        // Date+time: defer to ISO8601DateFormatter (handles the `T…Z` forms).
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let d = f.date(from: s) { return d }
        f.formatOptions = [.withInternetDateTime]
        if let d = f.date(from: s) { return d }
        return nil
    }

    /// `6 Feb 2026` — day, 3+ letter month, 4-digit year (regex `^(\d{1,2})\s+([A-Za-z]{3,})\s+(\d{4})$`).
    private static func parseDayMonthYear(_ s: String) -> Date? {
        guard let m = firstMatch(#"^(\d{1,2})\s+([A-Za-z]{3,})\s+(\d{4})$"#, in: s),
              let day = Int(m[1]), let year = Int(m[3]) else { return nil }
        let monPrefix = String(m[2].lowercased().prefix(3))
        guard let idx = monthAbbrevs.firstIndex(of: monPrefix) else { return nil }
        return localDate(year: year, month: idx + 1, day: day)
    }

    /// `M/D/YYYY` or `M/D/YY` (regex `^(\d{1,2})/(\d{1,2})/(\d{2,4})$`); 2-digit years → 2000+.
    private static func parseSlash(_ s: String) -> Date? {
        guard let m = firstMatch(#"^(\d{1,2})/(\d{1,2})/(\d{2,4})$"#, in: s),
              let mo = Int(m[1]), let d = Int(m[2]), var y = Int(m[3]) else { return nil }
        if y < 100 { y += 2000 }
        return localDate(year: y, month: mo, day: d)
    }

    // MARK: - helpers

    /// First 4-digit run anywhere in the string → its year, mirroring Dart's `_yearOf`
    /// (`RegExp(r'(\d{4})')`). Used by the by-year quorum/advancement rules.
    public static func yearOf(_ raw: String?) -> Int? {
        guard let raw, let m = firstMatch(#"(\d{4})"#, in: raw) else { return nil }
        return Int(m[1])
    }

    static func localDate(year: Int, month: Int, day: Int) -> Date? {
        var c = DateComponents()
        c.year = year; c.month = month; c.day = day
        c.hour = 0; c.minute = 0; c.second = 0
        return Calendar.current.date(from: c)
    }

    /// Returns capture groups (group 0 = whole match, then each capture) of the first match, or nil.
    private static func firstMatch(_ pattern: String, in s: String) -> [String]? {
        guard let re = try? NSRegularExpression(pattern: pattern) else { return nil }
        let range = NSRange(s.startIndex..<s.endIndex, in: s)
        guard let match = re.firstMatch(in: s, range: range) else { return nil }
        var groups: [String] = []
        for i in 0..<match.numberOfRanges {
            if let r = Range(match.range(at: i), in: s) {
                groups.append(String(s[r]))
            } else {
                groups.append("")
            }
        }
        return groups
    }
}
