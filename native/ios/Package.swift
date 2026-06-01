// swift-tools-version: 5.9
//
// CovenantPath — native iOS app (Swift + SwiftUI, iOS 17+).
//
// This package builds the app's sources as a library module (`CovenantPathKit`) so the pure logic
// (milestones, org buckets, date parsing, KPI bucketing, freshness) is unit-testable on the command
// line via `swift test`. The shipping app is built by XcodeGen/xcodebuild (see `project.yml`), which
// compiles the same `Sources/` + the `App/` shell directly and links supabase-swift — the xcodeproj
// does NOT reference this package. supabase-swift's resolved 2.x minor is whatever SwiftPM picks.
import PackageDescription

let package = Package(
    name: "CovenantPathKit",
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
                .product(name: "Supabase", package: "supabase-swift"),
                // `Auth` is a separate supabase-swift product; depend on it explicitly so `import Auth`
                // (Session / AuthChangeEvent / EmailOTPType) always resolves, not just transitively.
                .product(name: "Auth", package: "supabase-swift")
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
