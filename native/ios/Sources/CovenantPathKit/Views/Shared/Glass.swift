#if canImport(UIKit)
import SwiftUI

/// **Liquid-Glass design system** (iOS 26) with a frosted-material fallback for the iOS 17–25 floor.
///
/// Apple's real Liquid Glass (`.glassEffect`, `GlassEffectContainer`, `.buttonStyle(.glass)`) only
/// exists in the **iOS 26 SDK**, so every glass call is *double-gated*:
///
///   * `#if compiler(>=6.2)` — compile the glass branch ONLY when building with the Xcode 26 toolchain
///     (Swift 6.2 ships alongside the iOS 26 SDK). Older Xcodes compile the material fallback, so CI
///     stays green on any runner regardless of the installed Xcode.
///   * `if #available(iOS 26.0, *)` — at *runtime*, use glass on iOS 26 devices and the frosted
///     fallback on iOS 17–25. The app's deployment target stays **17.0**.
///
/// The result: one build runs everywhere, looks like genuine Liquid Glass on iOS 26, and degrades to a
/// clean translucent-material look on older devices. Call sites never repeat the gates — they just use
/// `.cpGlassCard()`, `.cpGlassChip(...)`, `CPGlassGroup { … }`, etc.
enum CP {
    /// Continuous corner radii tuned for iOS concentricity.
    static let cardRadius: CGFloat = 22
    static let chipRadius: CGFloat = 14
}

extension View {
    // MARK: Surfaces

    /// A floating glass **card** surface — the building block for `SectionCard` and dashboard panels.
    /// Apply to already-padded content (it provides the background, not the padding).
    @ViewBuilder
    func cpGlassCard(cornerRadius: CGFloat = CP.cardRadius) -> some View {
        let shape = RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
        #if compiler(>=6.2)
        if #available(iOS 26.0, *) {
            self.glassEffect(.regular, in: shape)
        } else {
            self.cpMaterialSurface(shape)
        }
        #else
        self.cpMaterialSurface(shape)
        #endif
    }

    /// A glass **capsule chip** — filter/category pills. `tint` colors the glass, `selected` raises its
    /// presence, `interactive` adds the touch-reactive sheen on iOS 26.
    @ViewBuilder
    func cpGlassChip(tint: Color, selected: Bool = false, interactive: Bool = true) -> some View {
        let shape = Capsule()
        #if compiler(>=6.2)
        if #available(iOS 26.0, *) {
            let base = selected ? Glass.regular.tint(tint.opacity(0.45)) : Glass.regular
            self.glassEffect(interactive ? base.interactive() : base, in: shape)
        } else {
            self.cpChipFallback(shape, tint: tint, selected: selected)
        }
        #else
        self.cpChipFallback(shape, tint: tint, selected: selected)
        #endif
    }

    /// A glass surface in an arbitrary shape (banners, the toast, small tiles).
    @ViewBuilder
    func cpGlass<S: InsettableShape>(in shape: S, tint: Color? = nil) -> some View {
        #if compiler(>=6.2)
        if #available(iOS 26.0, *) {
            self.glassEffect(tint.map { Glass.regular.tint($0.opacity(0.25)) } ?? .regular, in: shape)
        } else {
            self.cpTintedMaterial(shape, tint: tint)
        }
        #else
        self.cpTintedMaterial(shape, tint: tint)
        #endif
    }

    // MARK: Fallbacks (iOS 17–25)

    fileprivate func cpMaterialSurface<S: InsettableShape>(_ shape: S) -> some View {
        // No drop shadow: a per-card offscreen-rendered shadow is a real scroll-cost multiplier when
        // several cards scroll (KPIs has 5–7). The frosted material + a hairline edge reads as a card
        // without the blur compositing. (iOS 26 glass supplies its own cheap shadow on the other path.)
        self
            .background(.regularMaterial, in: shape)
            .overlay { shape.strokeBorder(Color.primary.opacity(0.10), lineWidth: 0.5) }
    }

    @ViewBuilder
    fileprivate func cpChipFallback<S: InsettableShape>(_ shape: S, tint: Color, selected: Bool) -> some View {
        if selected {
            self.background(tint.opacity(0.22), in: shape)
                .overlay { shape.strokeBorder(tint.opacity(0.85), lineWidth: 1) }
        } else {
            self.background(.ultraThinMaterial, in: shape)
                .overlay { shape.strokeBorder(tint.opacity(0.30), lineWidth: 1) }
        }
    }

    @ViewBuilder
    fileprivate func cpTintedMaterial<S: InsettableShape>(_ shape: S, tint: Color?) -> some View {
        if let tint {
            self.background(tint.opacity(0.12), in: shape).background(.ultraThinMaterial, in: shape)
        } else {
            // No tint (e.g. the toast): give the bare material a faint edge so it reads on a white
            // background (iOS 26 glass has its own edge, so this only applies on the fallback).
            self.background(.ultraThinMaterial, in: shape)
                .overlay { shape.strokeBorder(Color.primary.opacity(0.10), lineWidth: 0.5) }
        }
    }

    // MARK: Tab bar

    /// On iOS 26 the Liquid-Glass tab bar minimizes as you scroll down (and re-expands scrolling up),
    /// keeping more content on screen. No-op on the fallback. The tab bar already adopts Liquid Glass
    /// automatically when built with the iOS 26 SDK — this just opts into the scroll behavior.
    @ViewBuilder
    func cpTabBarMinimizeOnScroll() -> some View {
        #if compiler(>=6.2)
        if #available(iOS 26.0, *) {
            self.tabBarMinimizeBehavior(.onScrollDown)
        } else {
            self
        }
        #else
        self
        #endif
    }

    // MARK: Buttons

    /// A Liquid-Glass action button on iOS 26 (`.glass` / `.glassProminent`), falling back to
    /// `.bordered` / `.borderedProminent` below. Use on prominent action buttons so they match the
    /// glass system instead of looking like flat Material buttons.
    @ViewBuilder
    func cpGlassButton(prominent: Bool = false) -> some View {
        #if compiler(>=6.2)
        if #available(iOS 26.0, *) {
            if prominent { self.buttonStyle(.glassProminent) } else { self.buttonStyle(.glass) }
        } else {
            if prominent { self.buttonStyle(.borderedProminent) } else { self.buttonStyle(.bordered) }
        }
        #else
        if prominent { self.buttonStyle(.borderedProminent) } else { self.buttonStyle(.bordered) }
        #endif
    }

    // MARK: Screen backdrop

    /// A subtle, tab-tinted backdrop so the glass surfaces have something to refract over (Liquid Glass
    /// is meaningless on a flat fill). Stays restrained in both light and dark.
    func cpScreenBackground(_ accent: Color) -> some View {
        background { CPScreenBackground(accent: accent).ignoresSafeArea() }
    }
}

/// A glass *container* — on iOS 26 it lets adjacent `.glassEffect` shapes blend/merge fluidly; on the
/// fallback it's a transparent pass-through so the same chip rows just render as material capsules.
@ViewBuilder
func CPGlassGroup<Content: View>(spacing: CGFloat = 8, @ViewBuilder content: () -> Content) -> some View {
    #if compiler(>=6.2)
    if #available(iOS 26.0, *) {
        GlassEffectContainer(spacing: spacing) { content() }
    } else {
        content()
    }
    #else
    content()
    #endif
}

/// The tab-tinted screen backdrop (extracted so it can read the color scheme).
private struct CPScreenBackground: View {
    let accent: Color
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        LinearGradient(
            colors: [
                Color(.systemBackground),
                accent.opacity(scheme == .dark ? 0.12 : 0.05)
            ],
            startPoint: .top,
            endPoint: .bottom
        )
    }
}
#endif
