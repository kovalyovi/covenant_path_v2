import SwiftUI
import CovenantPathKit

/// The iOS app entry point. The whole app lives in the `CovenantPathKit` Swift package (so the pure
/// logic is unit-testable); this target is a thin shell that just renders `RootView`.
///
/// To create this target in Xcode: File → New → Target → App (SwiftUI lifecycle, iOS 17+), then add
/// the local `CovenantPath` package and link the `CovenantPathKit` library. See README.
@main
struct CovenantPathApp: App {
    var body: some Scene {
        WindowGroup {
            RootView()
        }
    }
}
