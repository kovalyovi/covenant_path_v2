import Foundation

/// Best-effort client error telemetry → broker `/log` (port of `error_reporter.dart`). No-op without
/// a broker URL. Sends only the error type, a truncated message, and a surface hint — NEVER PII.
///
/// iOS has no Flutter-style error zone, but we install an `NSSetUncaughtExceptionHandler` for
/// Objective-C exceptions and expose `report(_:where:)` so call sites (do/catch around async work)
/// can forward Swift errors explicitly.
public enum ErrorReporter {
    // A single sink set once at app start. `BrokerService` is `@unchecked Sendable`; under the 5.9
    // language mode used here this static is unchecked too (no strict-concurrency diagnostic).
    private static var broker: BrokerService?

    public static func install(broker: BrokerService) {
        self.broker = broker
        NSSetUncaughtExceptionHandler { exception in
            let msg = "\(exception.name.rawValue): \(exception.reason ?? "")"
            ErrorReporter.report(type: "NSException", message: msg, where: "uncaught")
        }
    }

    /// Report a Swift `Error` (type + message). Surface defaults to "native".
    public static func report(_ error: Error, where loc: String? = nil) {
        report(type: String(describing: Swift.type(of: error)),
               message: error.localizedDescription, where: loc)
    }

    public static func report(type: String, message: String, where loc: String?) {
        broker?.log(type: type, message: message, surface: "native", where: loc)
    }
}
