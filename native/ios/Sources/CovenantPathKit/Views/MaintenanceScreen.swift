#if canImport(UIKit)
import SwiftUI

/// Owner-only MAINTENANCE mode lock screen (migration 0056) — shown to everyone EXCEPT the owner while
/// the global switch is ON. Purely UX: the database's RESTRICTIVE RLS already returns no member rows to
/// non-owners during maintenance, so this just replaces the (empty) dashboard with a friendly message.
/// Mirrors the web `MaintenanceGate` "We'll be right back" screen.
struct MaintenanceScreen: View {
    let message: String?

    private var body_message: String {
        let trimmed = message?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return trimmed.isEmpty
            ? "Covenant Path is briefly down for maintenance. Please check back in a little while."
            : trimmed
    }

    var body: some View {
        VStack(spacing: 14) {
            Image(systemName: "wrench.and.screwdriver.fill")
                .font(.system(size: 44))
                .foregroundStyle(.secondary)
            Text("We'll be right back")
                .font(.title2.bold())
            Text(body_message)
                .font(.callout)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .frame(maxWidth: 420)
        }
        .padding(32)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color(.systemBackground))
        .ignoresSafeArea()
    }
}
#endif
