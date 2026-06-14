#if canImport(UIKit)
import Foundation
import os

/// Lightweight performance instrumentation for the dashboard, with two sinks:
///
///  • **On-device (always):** an `OSSignposter` interval + an `os.Logger` line per measurement. Open
///    **Instruments → os_signpost / Time Profiler** (or **Console.app**) on a Mac connected to the
///    device and filter subsystem `org.membercovenantpath.viewer` to see live spans/timings.
///  • **Remote (when a broker is configured):** every ~20s of activity, a compact per-metric summary
///    (`count / p50 / p90 / max` ms) is POSTed to the broker `/log`. The broker logs client events to
///    its stdout, so it can be **pulled with `python tools/render_logs.py --text PERF`** — no device
///    needed. Perf payloads are PII-free (metric names + millisecond timings), so they are NOT scrubbed.
///
/// Overhead is a timestamp + array append per sample; the network flush is throttled and fire-and-forget.
@MainActor
public enum Perf {
    private static let logger = Logger(subsystem: "org.membercovenantpath.viewer", category: "perf")
    private static let signposter = OSSignposter(subsystem: "org.membercovenantpath.viewer",
                                                 category: "perf")

    private static var samples: [String: [Double]] = [:]
    private static var sink: ((_ summary: String, _ context: [String: Any]) -> Void)?
    private static var flushScheduled = false
    private static let flushDelay: UInt64 = 20 * 1_000_000_000   // 20s

    /// Wire the remote summary sink (broker `/log`) once at app start.
    public static func setSink(_ s: @escaping (String, [String: Any]) -> Void) { sink = s }

    /// Measure a synchronous span: emits a signpost interval + records the elapsed ms under `key`.
    @discardableResult
    public static func measure<T>(_ key: String, _ body: () -> T) -> T {
        let state = signposter.beginInterval("span", id: signposter.makeSignpostID(), "\(key, privacy: .public)")
        let t0 = CFAbsoluteTimeGetCurrent()
        let result = body()
        let ms = (CFAbsoluteTimeGetCurrent() - t0) * 1000
        signposter.endInterval("span", state)
        record(key, ms: ms)
        return result
    }

    /// Record a precomputed duration (e.g. a tab-switch latency derived from timestamps).
    public static func record(_ key: String, ms: Double) {
        logger.debug("\(key, privacy: .public) \(ms, privacy: .public)ms")
        samples[key, default: []].append(ms)
        scheduleFlush()
    }

    /// Record the elapsed ms since a `CFAbsoluteTimeGetCurrent()` timestamp.
    public static func record(_ key: String, since start: CFAbsoluteTime) {
        record(key, ms: (CFAbsoluteTimeGetCurrent() - start) * 1000)
    }

    private static func scheduleFlush() {
        guard !flushScheduled, sink != nil else { return }
        flushScheduled = true
        Task { @MainActor in
            try? await Task.sleep(nanoseconds: flushDelay)
            flushScheduled = false
            flush()
        }
    }

    /// Summarize buffered samples (count / p50 / p90 / max ms) and ship one line per metric.
    public static func flush() {
        guard let sink, !samples.isEmpty else { return }
        let snapshot = samples
        samples.removeAll(keepingCapacity: true)
        for (key, values) in snapshot where !values.isEmpty {
            let sorted = values.sorted()
            func pct(_ q: Double) -> Double {
                sorted[max(0, min(sorted.count - 1, Int((q * Double(sorted.count)).rounded(.down))))]
            }
            let p50 = pct(0.5), p90 = pct(0.9), mx = sorted.last ?? 0
            let summary = String(format: "PERF %@ n=%d p50=%.0f p90=%.0f max=%.0f",
                                 key, values.count, p50, p90, mx)
            logger.info("\(summary, privacy: .public)")
            sink(summary, ["metric": key, "n": values.count,
                           "p50_ms": Int(p50.rounded()), "p90_ms": Int(p90.rounded()),
                           "max_ms": Int(mx.rounded())])
        }
    }
}
#endif
