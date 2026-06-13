#if canImport(UIKit)
import SwiftUI

/// The org-ownership filter bar (Golden Hour + Needs): a colored toggle per org (WML / EQ / RS), ALL
/// selected by default. Tapping a chip toggles whether that org's converts are shown (multi-select,
/// additive); you can't deselect the last one (→ empty). When not all three are on, a "Clear filters"
/// chip restores them. Colors come from `Org.info` so they stay consistent with the per-member
/// responsibility chips. Faithful port of `_OrgFilterBar` + the `_toggleOrg` guard.
public struct OrgFilterBar: View {
    @Binding var selected: Set<OrgBucket>

    public init(selected: Binding<Set<OrgBucket>>) { self._selected = selected }

    private var allSelected: Bool { selected.count == OrgBucket.allCases.count }

    /// Toggle that never lets the user deselect the last org (delegates to the pure `Org.toggleFilter`
    /// so the rule has one home and stays unit-testable without UIKit).
    public static func toggle(_ b: OrgBucket, in set: inout Set<OrgBucket>) {
        Org.toggleFilter(b, in: &set)
    }

    public var body: some View {
        // Liquid-Glass capsules (frosted-material fallback on iOS 17–25). The glass container lets the
        // adjacent chips blend fluidly on iOS 26.
        CPGlassGroup(spacing: 6) {
            FlowLayout(spacing: 6) {
                ForEach(OrgBucket.allCases) { b in
                    let info = Org.info(b)
                    let color = Color(hex: info.hex)
                    let sel = selected.contains(b)
                    Button {
                        OrgFilterBar.toggle(b, in: &selected)
                    } label: {
                        HStack(spacing: 6) {
                            Image(systemName: info.symbol).font(.system(size: 14))
                                .foregroundStyle(color)
                            Text(info.label)
                                .font(.system(size: 13, weight: sel ? .bold : .medium))
                                .foregroundStyle(sel ? color : color.opacity(0.65))
                        }
                        .padding(.horizontal, 13).padding(.vertical, 8)
                        .cpGlassChip(tint: color, selected: sel)
                    }
                    .buttonStyle(.plain)
                }
                if !allSelected {
                    Button {
                        selected = Set(OrgBucket.allCases)
                    } label: {
                        HStack(spacing: 6) {
                            Image(systemName: "line.3.horizontal.decrease.circle").font(.system(size: 14))
                            Text("Clear filters").font(.system(size: 13))
                        }
                        .padding(.horizontal, 13).padding(.vertical, 8)
                        .cpGlassChip(tint: Color(.secondaryLabel), selected: false)
                    }
                    .buttonStyle(.plain)
                    .foregroundStyle(.secondary)
                }
            }
        }
        .frame(maxWidth: .infinity)
    }
}

/// A centered, muted one-liner (the org-responsibility explanation under the filter). Mirrors
/// `_SubtleNote`.
public struct SubtleNote: View {
    let text: String
    public init(_ text: String) { self.text = text }
    public var body: some View {
        Text(text)
            .font(.caption)
            .foregroundStyle(.secondary)
            .multilineTextAlignment(.center)
            .frame(maxWidth: .infinity)
            .padding(.horizontal, 20)
    }
}
#endif
