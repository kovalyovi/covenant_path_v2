import Foundation

/// The CLIENT DISPLAY CONTRACT for any covenant-path field value, applied everywhere a field is shown
/// (table, cards, details). Faithful port of web `apps/web/src/logic/fieldDisplay.ts` +
/// `apps/web/src/lib/member.ts` (`isSentinel`/`isAdminSentinel`/`displayFieldValue`).
///
/// Three outcomes for a field value:
///   • a real value (Yes/No/Active/a date/…)  → `.value`  → show it verbatim.
///   • "N/A"                                   → `.na`     → NOT ELIGIBLE; show quietly as "N/A"
///                                                            (or OMIT in Golden Hour). NEVER a warning.
///   • the "needs-profile-api" sentinel, a "blocked: …" sentinel, OR null/empty
///                                             → `.issue`  → a DATA ISSUE (we should have it but
///                                                            don't); show a ⚠ warning indicator,
///                                                            NEVER the raw sentinel string.
///
/// Critically — per the user's rule — the sentinel AND null/empty are treated THE SAME: both are a
/// ⚠ data issue. An ADMIN may see the raw sentinel string (to diagnose); a regular leader never does.

/// The backend's internal sentinels (mirror `covenant_path/report.py` + `backend/db.py _SENTINELS`).
/// The merge-upsert writes these when a field couldn't be fetched this run (preserving last-good).
/// They are TECHY/internal — only ADMINS should ever see the raw value.
public enum FieldSentinel {
    public static let needsProfile = "needs-profile-api"
    public static let blockedPrefix = "blocked"   // e.g. "blocked: insufficient calling access"

    /// True when a value is one of the backend's internal sentinels (not real member data).
    public static func isSentinel(_ value: String?) -> Bool {
        let s = (value ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        return s == needsProfile || s.hasPrefix(blockedPrefix)
    }

    /// Alias of `isSentinel` for the field-display contract — names the case where there's a raw,
    /// TECHY sentinel string an admin MAY be shown for diagnosis (vs a plain empty/missing value,
    /// which is a data issue too but carries no string to surface). Mirrors web `isAdminSentinel`.
    public static func isAdminSentinel(_ value: String?) -> Bool { isSentinel(value) }
}

/// The three-way classification of a field value (mirrors web `FieldStatus`).
public enum FieldStatus: Sendable, Equatable {
    case value   // a real value — show `text` verbatim
    case na      // "N/A" — not eligible; quiet, never a warning
    case issue   // a data issue — show ⚠; `text` is the raw sentinel for admins, "" otherwise
}

/// What to render for a field value, audience-aware (mirrors web `FieldDisplay`).
public struct FieldDisplay: Sendable, Equatable {
    public let status: FieldStatus
    /// What to render as text: the real value, the literal "N/A", or "" for a data issue (the caller
    /// shows a ⚠ indicator instead of text). For an admin a data-issue value keeps the raw sentinel
    /// so they can diagnose it; a leader never sees the techy string.
    public let text: String
    /// True only for `.issue` — the caller renders a ⚠ warning indicator.
    public var warn: Bool { status == .issue }

    public init(status: FieldStatus, text: String) {
        self.status = status; self.text = text
    }
}

public enum FieldDisplayLogic {

    /// "N/A" — not-eligible (a woman's priesthood, a child's patriarchal blessing). Mirrors web `isNA`.
    public static func isNA(_ value: String?) -> Bool {
        (value ?? "").trimmingCharacters(in: .whitespacesAndNewlines).uppercased() == "N/A"
    }

    /// Classify a field value into the display contract above (mirrors web `fieldDisplay`).
    ///  - `isAdmin` only affects a data ISSUE: an admin sees the raw sentinel as the text (still
    ///    warn:true) so they can diagnose "needs-profile-api"/"blocked: …"; a leader sees empty text
    ///    + the ⚠ only.
    public static func classify(_ value: String?, isAdmin: Bool = false) -> FieldDisplay {
        // N/A first — "not eligible" is a quiet, legitimate state, never a warning.
        if isNA(value) { return FieldDisplay(status: .na, text: "N/A") }
        let s = (value ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        // The backend sentinel OR an empty/missing value are BOTH a data issue (treated the same).
        if s.isEmpty || FieldSentinel.isSentinel(s) {
            // Admins keep the raw sentinel string for diagnosis (only when it IS a sentinel — an empty
            // value has nothing techy to show); leaders never see it.
            let adminText = (isAdmin && FieldSentinel.isAdminSentinel(s)) ? s : ""
            return FieldDisplay(status: .issue, text: adminText)
        }
        return FieldDisplay(status: .value, text: s)
    }

    /// Convenience: is this value a data issue (sentinel OR null/empty, but NOT N/A)? Mirrors web
    /// `isDataIssue`.
    public static func isDataIssue(_ value: String?) -> Bool {
        classify(value).status == .issue
    }
}
