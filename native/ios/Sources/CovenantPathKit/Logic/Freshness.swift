import Foundation

/// Data-freshness helpers, ported from `dashboard_common.dart` (`_ago`, `_staleColor`) and
/// `dashboard_page._LastUpdated`. Pure (no UI) so it's testable; the view maps `Staleness` → a color.
public enum Freshness {

    /// Parse a Supabase/ISO timestamp (with or without fractional seconds).
    public static func parse(_ iso: String?) -> Date? {
        guard let iso, !iso.isEmpty else { return nil }
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let d = f.date(from: iso) { return d }
        f.formatOptions = [.withInternetDateTime]
        if let d = f.date(from: iso) { return d }
        // Fall back to a plain date (e.g. "2026-05-30").
        return MemberDate.parse(iso)
    }

    /// "2h ago" style relative string (port of `_ago`). Minutes <60, then hours <24, then days.
    public static func ago(_ iso: String?, now: Date = Date()) -> String {
        guard let t = parse(iso) else { return iso ?? "" }
        let secs = now.timeIntervalSince(t)
        let mins = Int(secs / 60), hours = Int(secs / 3600), days = Int(secs / 86400)
        if mins < 60 { return "\(max(0, mins))m ago" }
        if hours < 24 { return "\(hours)h ago" }
        return "\(days)d ago"
    }

    /// Exact local time string, e.g. "May 30, 2026 · 2:14 PM" + tz — mirrors `_LastUpdated._exact`.
    public static func exact(_ iso: String?) -> String {
        guard let t = parse(iso) else { return iso ?? "" }
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US")
        f.dateFormat = "MMM d, y · h:mm a"
        let z = TimeZone.current.abbreviation() ?? ""
        return "\(f.string(from: t)) \(z)"
    }

    /// Staleness tier for a last-synced timestamp (port of `_staleColor`): never→red, ≥14d→red,
    /// ≥2d→amber, else fresh. The view maps these to red/amber/none.
    public enum Staleness: Sendable { case fresh, amber, red }

    public static func staleness(_ iso: String?, now: Date = Date()) -> Staleness {
        guard let t = parse(iso) else { return .red }   // never synced reads as stale
        let days = Int(now.timeIntervalSince(t) / 86400)
        if days >= 14 { return .red }
        if days >= 2 { return .amber }
        return .fresh
    }
}
