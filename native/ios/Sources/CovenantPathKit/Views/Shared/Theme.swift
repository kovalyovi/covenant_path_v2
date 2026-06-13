#if canImport(UIKit)
import SwiftUI

/// Color helpers + the per-tab accent palette. Hex values come straight from the Flutter app so the
/// native PoC reads with the same color identities (status green/amber/red, org teal/blue/rose, the
/// distinct nav palette).
public extension Color {
    /// Build a Color from a 0xRRGGBB integer (the form used throughout the ported logic).
    init(hex: UInt32) {
        let r = Double((hex >> 16) & 0xFF) / 255.0
        let g = Double((hex >> 8) & 0xFF) / 255.0
        let b = Double(hex & 0xFF) / 255.0
        self.init(.sRGB, red: r, green: g, blue: b, opacity: 1)
    }
}

/// Status colors used by chips/dots/cells (match the Flutter Material shades closely).
public enum StatusColor {
    public static let done = Color(hex: 0x43A047)   // green 600
    public static let next = Color(hex: 0xFFB300)   // amber 700
    public static let off  = Color(hex: 0x9E9E9E)   // grey 500
    public static let yes  = Color(hex: 0xC8E6C9)   // green 100 bg
    public static let no   = Color(hex: 0xFFCDD2)   // red 100 bg
    public static let na   = Color(hex: 0xEEEEEE)   // grey 200 bg
    public static let expired = Color(hex: 0xFFE082) // amber 200 bg
}

/// The 5 dashboard tabs, each with its own accent color + SF Symbol (mirrors `_tabs`).
public enum DashboardTab: Int, CaseIterable, Identifiable {
    // "By Month" is no longer its own tab — the baptisms-by-month chart now lives at the bottom of KPIs (#1).
    case baptisms, goldenHour, needs, kpis, table
    public var id: Int { rawValue }

    public var title: String {
        switch self {
        case .baptisms: return "Baptisms"
        case .goldenHour: return "Golden Hour"
        case .needs: return "Needs"
        case .kpis: return "KPIs"
        case .table: return "Table"
        }
    }

    public var symbol: String {
        switch self {
        case .baptisms: return "calendar.badge.checkmark"
        case .goldenHour: return "hourglass"
        case .needs: return "checklist"
        case .kpis: return "chart.line.uptrend.xyaxis"
        case .table: return "tablecells"
        }
    }

    public var accent: Color {
        switch self {
        case .baptisms: return Color(hex: 0x0277BD)   // blue
        case .goldenHour: return Color(hex: 0xF9A825)  // gold/amber
        case .needs: return Color(hex: 0xD84315)       // deep orange
        case .kpis: return Color(hex: 0x2E7D32)        // green
        case .table: return Color(hex: 0x5E35B1)       // deep purple
        }
    }
}

/// A titled rounded-card section — the building block for detail + list pages (mirrors `SectionCard`).
public struct SectionCard<Content: View>: View {
    let title: String
    let systemImage: String?
    let iconColor: Color?
    let leading: AnyView?
    let trailing: AnyView?
    @ViewBuilder let content: () -> Content

    public init(title: String, systemImage: String? = nil, iconColor: Color? = nil,
                leading: AnyView? = nil, trailing: AnyView? = nil,
                @ViewBuilder content: @escaping () -> Content) {
        self.title = title; self.systemImage = systemImage; self.iconColor = iconColor
        self.leading = leading; self.trailing = trailing; self.content = content
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 10) {
                if let leading {
                    leading   // custom leading element (e.g. a completion ring) replaces the glyph
                } else if let systemImage {
                    let accent = iconColor ?? .accentColor
                    Image(systemName: systemImage)
                        .font(.system(size: 16, weight: .semibold))
                        .foregroundStyle(accent)
                        .frame(width: 32, height: 32)
                        // A solid tinted glyph chip — NOT glass — so we never nest glass inside the card.
                        .background(accent.opacity(0.16), in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                }
                Text(title).font(.headline)
                Spacer(minLength: 0)
                if let trailing { trailing }
            }
            content()
        }
        .padding(18)
        .frame(maxWidth: .infinity, alignment: .leading)
        // Liquid Glass on iOS 26, frosted material on iOS 17–25 — one surface for every panel app-wide.
        .cpGlassCard()
    }
}

/// A small rounded count badge (mirrors `_CountBadge`).
public struct CountBadge: View {
    let count: Int
    public init(_ count: Int) { self.count = count }
    public var body: some View {
        Text("\(count)")
            .font(.caption.bold())
            .padding(.horizontal, 9).padding(.vertical, 2)
            .background(Color.accentColor.opacity(0.16), in: Capsule())
            .foregroundStyle(Color.accentColor)
    }
}

/// Semantic status colors (meaning-named) — mirrors `theme/tokens.dart` `AppColors`.
public enum AppColors {
    public static let success = Color(hex: 0x2E7D32)
    public static let warning = Color(hex: 0xEF6C00)
    public static let info = Color(hex: 0x1E88E5)
    public static let danger = Color(hex: 0xE53935)
    public static let neutral = Color(hex: 0x616161)
}

public extension Freshness.Staleness {
    /// Color for the freshness chip (port of `_staleColor`): amber after 2 days, red after 2 weeks,
    /// nil (default/fresh) otherwise.
    var color: Color? {
        switch self {
        case .fresh: return nil
        case .amber: return Color(hex: 0xFFB300)   // amber 700
        case .red:   return Color(hex: 0xE53935)   // red 600
        }
    }
}

/// A colored status tag (admin enrolled-stakes). Mirrors `StatusTag`.
public struct StatusTag: View {
    let text: String
    let color: Color
    public init(_ text: String, color: Color) { self.text = text; self.color = color }
    public var body: some View {
        Text(text)
            .font(.caption.weight(.semibold))
            .padding(.horizontal, 8).padding(.vertical, 2)
            .background(color.opacity(0.14), in: Capsule())
            .foregroundStyle(color)
    }
}

/// An ok/off status pill (admin health/diagnostics). Mirrors `StatusPill`.
public struct StatusPill: View {
    let label: String
    let ok: Bool
    var offText: String?
    public init(label: String, ok: Bool, offText: String? = nil) {
        self.label = label; self.ok = ok; self.offText = offText
    }
    public var body: some View {
        HStack(spacing: 5) {
            Image(systemName: ok ? "checkmark.circle.fill" : "xmark.circle.fill")
                .font(.caption)
            Text(ok ? label : (offText.map { "\(label) — \($0)" } ?? label)).font(.caption.weight(.medium))
        }
        .foregroundStyle(ok ? AppColors.success : AppColors.danger)
        .padding(.horizontal, 10).padding(.vertical, 5)
        .background((ok ? AppColors.success : AppColors.danger).opacity(0.12), in: Capsule())
    }
}
#endif
