#if canImport(UIKit)
import SwiftUI

/// A shimmering placeholder used while the first member load is in flight, so the layout doesn't pop
/// in (echoes the Flutter app's `MemberListSkeleton`). A few card-shaped rows with a moving sheen.
public struct MemberListSkeleton: View {
    public init() {}
    public var body: some View {
        ScrollView {
            VStack(spacing: 12) {
                ForEach(0..<6, id: \.self) { _ in
                    SkeletonCard()
                }
            }
            .padding(16)
        }
        .allowsHitTesting(false)
    }
}

struct SkeletonCard: View {
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 12) {
                Circle().frame(width: 44, height: 44)
                VStack(alignment: .leading, spacing: 8) {
                    RoundedRectangle(cornerRadius: 4).frame(width: 160, height: 12)
                    RoundedRectangle(cornerRadius: 4).frame(width: 100, height: 10)
                }
                Spacer()
            }
            HStack(spacing: 6) {
                ForEach(0..<5, id: \.self) { _ in Circle().frame(width: 22, height: 22) }
            }
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color(.secondarySystemGroupedBackground), in: RoundedRectangle(cornerRadius: 16))
        .redacted(reason: .placeholder)
        .shimmer()
    }
}

/// Skeleton for the Sync-settings sheet (port of `SyncSettingsSkeleton`): title + label/value rows
/// + a button block, shown the instant the sheet opens so it never jumps from blank → content.
public struct SyncSettingsSkeleton: View {
    public init() {}
    public var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            RoundedRectangle(cornerRadius: 6).frame(width: 160, height: 22)
            ForEach(0..<5, id: \.self) { _ in
                HStack {
                    RoundedRectangle(cornerRadius: 4).frame(width: 90, height: 12)
                    RoundedRectangle(cornerRadius: 4).frame(maxWidth: .infinity).frame(height: 12)
                }
            }
            RoundedRectangle(cornerRadius: 8).frame(maxWidth: .infinity).frame(height: 44)
        }
        .redacted(reason: .placeholder)
        .shimmer()
    }
}

/// Generic skeleton of a few text lines for detail/secondary panels (comments, admin). Port of
/// `CardSkeleton`.
public struct CardSkeleton: View {
    let lines: Int
    public init(lines: Int = 3) { self.lines = lines }
    public var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            ForEach(0..<lines, id: \.self) { i in
                RoundedRectangle(cornerRadius: 4)
                    .frame(maxWidth: .infinity).frame(height: 12)
                    .frame(width: i % 2 == 0 ? nil : 180, alignment: .leading)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .redacted(reason: .placeholder)
        .shimmer()
    }
}

/// #16: small placeholder for the sync-settings schedule / Drive sub-sections while their broker
/// calls resolve — so they fade in as a skeleton instead of abruptly appearing once loaded.
public struct SyncSubsectionSkeleton: View {
    public init() {}
    public var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Divider().padding(.vertical, 8)
            CardSkeleton(lines: 2)
        }
    }
}

// MARK: - N8 content-shaped tab skeletons

/// A rounded card shaped like `SectionCard` (same background + corner radius + padding) so the
/// KPI / Golden-Hour skeletons occupy the real card footprint — no layout jump when data lands.
private struct SkelCard<Content: View>: View {
    private let content: Content
    init(@ViewBuilder content: () -> Content) { self.content = content() }
    var body: some View {
        VStack(alignment: .leading, spacing: 12) { content }
            .padding(16)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Color(.secondarySystemGroupedBackground), in: RoundedRectangle(cornerRadius: 16))
    }
}

/// One member-row placeholder (avatar + two lines + trailing chip), no self-shimmer — the outer
/// skeleton applies one sweep across the whole tree.
private struct SkelMemberRow: View {
    var body: some View {
        HStack(spacing: 12) {
            Circle().frame(width: 44, height: 44)
            VStack(alignment: .leading, spacing: 8) {
                RoundedRectangle(cornerRadius: 4).frame(width: 160, height: 12)
                RoundedRectangle(cornerRadius: 4).frame(width: 100, height: 10)
            }
            Spacer()
            RoundedRectangle(cornerRadius: 11).frame(width: 52, height: 22)
        }
    }
}

/// N8: content-shaped skeleton for the Golden Hour tab — the section toggle, org filter chips and
/// window selector, the "Golden Hour completion" card (a flow of % stats matching `pctStat` at
/// width 124), then the per-unit member grid. Mirrors `GoldenHourView` so nothing shifts on load.
public struct GoldenHourSkeleton: View {
    public init() {}
    public var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                RoundedRectangle(cornerRadius: 8).frame(height: 32)              // section picker
                HStack(spacing: 6) {                                             // org filter chips
                    ForEach(0..<3, id: \.self) { _ in Capsule().frame(width: 64, height: 30) }
                }
                .frame(maxWidth: .infinity, alignment: .center)
                RoundedRectangle(cornerRadius: 8).frame(width: 260, height: 30)  // window selector
                    .frame(maxWidth: .infinity, alignment: .center)
                HStack {                                                         // section title row
                    RoundedRectangle(cornerRadius: 4).frame(width: 170, height: 18)
                    Spacer()
                    RoundedRectangle(cornerRadius: 15).frame(width: 120, height: 30)
                }
                SkelCard {                                                       // completion card
                    RoundedRectangle(cornerRadius: 4).frame(width: 190, height: 16)
                    FlowLayout(spacing: 18, lineSpacing: 12) {
                        ForEach(0..<6, id: \.self) { _ in pctStat }
                    }
                }
                ForEach(0..<2, id: \.self) { _ in                                // per-unit grid
                    RoundedRectangle(cornerRadius: 4).frame(width: 140, height: 14)
                    ForEach(0..<3, id: \.self) { _ in SkelMemberRow() }
                }
            }
            .padding(16)
        }
        .allowsHitTesting(false)
        .redacted(reason: .placeholder)
        .shimmer()
    }
    private var pctStat: some View {
        VStack(alignment: .leading, spacing: 6) {
            RoundedRectangle(cornerRadius: 4).frame(width: 54, height: 20)
            RoundedRectangle(cornerRadius: 4).frame(width: 100, height: 10)
            RoundedRectangle(cornerRadius: 3).frame(width: 110, height: 5)
        }
        .frame(width: 124, alignment: .leading)
    }
}

/// N8: content-shaped skeleton for the KPIs tab — the big header + period selector, two chart cards
/// (the first carrying the Baptisms window selector) with the two big stats + 170-pt chart block +
/// caption, and the Overview stat grid. Mirrors `KPIsView`.
public struct KpiSkeleton: View {
    public init() {}
    public var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                HStack(alignment: .top, spacing: 10) {                           // big header
                    RoundedRectangle(cornerRadius: 2).frame(width: 4, height: 34)
                    VStack(alignment: .leading, spacing: 8) {
                        RoundedRectangle(cornerRadius: 4).frame(width: 90, height: 22)
                        RoundedRectangle(cornerRadius: 4).frame(width: 200, height: 11)
                    }
                    Spacer()
                }
                RoundedRectangle(cornerRadius: 8).frame(width: 220, height: 32)  // period selector
                    .frame(maxWidth: .infinity, alignment: .center)
                chartCard(withWindow: true)                                      // Baptisms
                chartCard(withWindow: false)                                     // a metric chart
                SkelCard {                                                       // Overview grid
                    RoundedRectangle(cornerRadius: 4).frame(width: 110, height: 16)
                    FlowLayout(spacing: 24, lineSpacing: 16) {
                        ForEach(0..<4, id: \.self) { _ in overviewStat }
                    }
                }
            }
            .padding(16)
            .frame(maxWidth: 760)
            .frame(maxWidth: .infinity)
        }
        .allowsHitTesting(false)
        .redacted(reason: .placeholder)
        .shimmer()
    }
    private func chartCard(withWindow: Bool) -> some View {
        SkelCard {
            HStack(spacing: 10) {                                                // icon + title
                RoundedRectangle(cornerRadius: 10).frame(width: 32, height: 32)
                RoundedRectangle(cornerRadius: 4).frame(width: 150, height: 16)
            }
            if withWindow {
                RoundedRectangle(cornerRadius: 8).frame(width: 260, height: 30)  // window selector
                    .frame(maxWidth: .infinity, alignment: .center)
            }
            HStack(spacing: 28) { stat; stat }                                   // two big stats
            RoundedRectangle(cornerRadius: 12).frame(height: 170)                // chart area
            RoundedRectangle(cornerRadius: 4).frame(width: 220, height: 10)      // caption
        }
    }
    private var stat: some View {
        VStack(alignment: .leading, spacing: 6) {
            RoundedRectangle(cornerRadius: 4).frame(width: 70, height: 10)
            RoundedRectangle(cornerRadius: 4).frame(width: 50, height: 22)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
    private var overviewStat: some View {
        VStack(alignment: .leading, spacing: 8) {
            RoundedRectangle(cornerRadius: 4).frame(width: 46, height: 24)
            RoundedRectangle(cornerRadius: 4).frame(width: 100, height: 10)
        }
        .frame(width: 124, alignment: .leading)
    }
}

// MARK: - shimmer modifier

extension View {
    func shimmer() -> some View { modifier(Shimmer()) }
}

struct Shimmer: ViewModifier {
    @State private var phase: CGFloat = -1
    func body(content: Content) -> some View {
        content
            .overlay(
                GeometryReader { geo in
                    LinearGradient(
                        colors: [.clear, Color.white.opacity(0.35), .clear],
                        startPoint: .leading, endPoint: .trailing
                    )
                    .frame(width: geo.size.width * 0.6)
                    .offset(x: phase * geo.size.width * 1.6)
                    .blendMode(.plusLighter)
                }
            )
            .mask(content)
            .onAppear {
                withAnimation(.linear(duration: 1.2).repeatForever(autoreverses: false)) {
                    phase = 1
                }
            }
    }
}
#endif
