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
    let trailing: AnyView?
    @ViewBuilder let content: () -> Content

    public init(title: String, systemImage: String? = nil, iconColor: Color? = nil,
                trailing: AnyView? = nil, @ViewBuilder content: @escaping () -> Content) {
        self.title = title; self.systemImage = systemImage; self.iconColor = iconColor
        self.trailing = trailing; self.content = content
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 10) {
                if let systemImage {
                    let accent = iconColor ?? .accentColor
                    Image(systemName: systemImage)
                        .font(.system(size: 16, weight: .semibold))
                        .foregroundStyle(accent)
                        .frame(width: 32, height: 32)
                        .background(accent.opacity(0.14), in: RoundedRectangle(cornerRadius: 10))
                }
                Text(title).font(.headline)
                Spacer(minLength: 0)
                if let trailing { trailing }
            }
            content()
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color(.secondarySystemGroupedBackground),
                    in: RoundedRectangle(cornerRadius: 16))
        .overlay(RoundedRectangle(cornerRadius: 16)
            .stroke(Color(.separator).opacity(0.5), lineWidth: 1))
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
#endif
