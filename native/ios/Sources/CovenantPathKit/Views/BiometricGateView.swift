#if canImport(UIKit)
import SwiftUI

/// Shows [content] once unlocked. The app-lock is **opt-in and OFF by default** (see
/// `BiometricService.enabled`), so the common path computes `unlocked == true` synchronously in `init`
/// and renders the dashboard immediately — no lock screen, no flash, no Face ID prompt. Only when a
/// leader has explicitly enabled App Lock do we gate and auto-prompt once.
struct BiometricGateView<Content: View>: View {
    @ViewBuilder var content: () -> Content

    @State private var unlocked: Bool
    @State private var prompted = false

    init(@ViewBuilder content: @escaping () -> Content) {
        self.content = content
        // Decide up front so a disabled lock never even renders the lock screen for a frame.
        #if canImport(LocalAuthentication)
        let shouldLock = BiometricService.enabled() && BiometricService.available()
        _unlocked = State(initialValue: !shouldLock)
        #else
        _unlocked = State(initialValue: true)
        #endif
    }

    var body: some View {
        Group {
            if unlocked {
                content()
            } else {
                lockScreen
            }
        }
        // Auto-prompt once when (and only when) the opt-in lock is engaged.
        .task {
            guard !unlocked, !prompted else { return }
            prompted = true
            await unlock()
        }
    }

    private var lockScreen: some View {
        VStack(spacing: 16) {
            Image(systemName: "lock")
                .font(.system(size: 48)).foregroundStyle(.tint)
            Text("Covenant Path is locked")
            Button {
                Task { await unlock() }
            } label: {
                Label("Unlock", systemImage: "faceid")
            }
            .cpGlassButton(prominent: true)
        }
        .padding(32)
    }

    private func unlock() async {
        #if canImport(LocalAuthentication)
        if await BiometricService.authenticate() { unlocked = true }
        #else
        unlocked = true
        #endif
    }
}
#endif
