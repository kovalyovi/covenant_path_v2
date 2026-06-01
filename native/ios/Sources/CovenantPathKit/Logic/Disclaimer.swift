import Foundation

/// Not-an-official-Church-app disclaimers, in one place so every surface stays consistent.
/// Verbatim ports of `apps/viewer/lib/disclaimer.dart`.
public enum Disclaimer {
    public static let short =
        "Independent tool · not affiliated with or endorsed by the Church · built by ILYA Kovalyov."

    public static let long =
        "Covenant Path is an independent tool built by ILYA Kovalyov to help leaders track new and "
        + "prospective members' covenant path. It is NOT an official product of The Church of Jesus "
        + "Christ of Latter-day Saints."

    public static let privacy =
        "Sign in with your Church (LCR) account is used to retrieve your stake's data on your behalf. "
        + "Your session is stored encrypted — your password is never stored — access is scoped to your "
        + "calling, and you can revoke it at any time."
}
