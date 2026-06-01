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
