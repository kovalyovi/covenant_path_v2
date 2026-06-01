#if canImport(UIKit)
import SwiftUI

/// Shows [content] once unlocked. When the lock is off/unavailable, shows it immediately (fail-open
/// on availability so a device without biometrics is never locked out). Port of `BiometricGate`.
struct BiometricGateView<Content: View>: View {
    @ViewBuilder var content: () -> Content

    @State private var unlocked = false
    @State private var checking = true

    var body: some View {
        Group {
            if unlocked {
                content()
            } else {
                lockScreen
            }
        }
        .task { await maybeLock() }
    }

    private var lockScreen: some View {
        VStack(spacing: 16) {
            if checking {
                ProgressView()
            } else {
                Image(systemName: "lock")
                    .font(.system(size: 48)).foregroundStyle(.tint)
                Text("Covenant Path is locked")
                Button {
                    Task { await unlock() }
                } label: {
                    Label("Unlock", systemImage: "faceid")
                }
                .buttonStyle(.borderedProminent)
            }
        }
        .padding(32)
    }

    private func maybeLock() async {
        #if canImport(LocalAuthentication)
        let shouldLock = BiometricService.enabled() && BiometricService.available()
        if !shouldLock {
            unlocked = true; checking = false
            return
        }
        checking = false
        await unlock()
        #else
        unlocked = true; checking = false
        #endif
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
