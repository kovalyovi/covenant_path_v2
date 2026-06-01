// swift-tools-version: 5.9
//
// CovenantPath — native iOS PoC (Swift + SwiftUI, iOS 17+).
//
// This package holds the entire app as a library module (`CovenantPathKit`) so the pure
// logic (milestones, org buckets, date parsing) is unit-testable on the command line, and a
// thin iOS app target in Xcode just imports it and renders `RootView`.
//
// The Supabase dependency is declared here via SwiftPM. We could not run `swift build` in the
// authoring environment (no macOS toolchain), so the resolved version is whatever SwiftPM
// picks in the 2.x line at first open in Xcode — see README "Dependencies".
import PackageDescription

let package = Package(
    name: "CovenantPath",
    platforms: [
        .iOS(.v17),
        .macOS(.v14) // lets the pure-logic tests run on a Mac dev box / CI without a simulator
    ],
    products: [
        .library(name: "CovenantPathKit", targets: ["CovenantPathKit"])
    ],
    dependencies: [
        // Official Supabase Swift SDK. 2.x is the current major line.
        .package(url: "https://github.com/supabase/supabase-swift.git", from: "2.20.0")
    ],
    targets: [
        .target(
            name: "CovenantPathKit",
            dependencies: [
                .product(name: "Supabase", package: "supabase-swift")
            ],
            path: "Sources/CovenantPathKit"
        ),
        .testTarget(
            name: "CovenantPathKitTests",
            dependencies: ["CovenantPathKit"],
            path: "Tests/CovenantPathKitTests"
        )
    ]
)
