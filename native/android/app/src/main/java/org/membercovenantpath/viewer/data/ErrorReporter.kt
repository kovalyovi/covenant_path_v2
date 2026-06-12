package org.membercovenantpath.viewer.data

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject

/**
 * Best-effort client error telemetry → broker `/log` (#53 parity). No-op without a broker URL.
 * Sends only the error type, a truncated message, and a surface hint — NEVER member data (no PII).
 * Ported from error_reporter.dart; installed as the JVM uncaught-exception handler in MainActivity.
 */
object ErrorReporter {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    // CLIENT-04: strip obvious PII (emails, URLs, long digit runs) before telemetry leaves the device.
    internal fun scrub(s: String): String =
        s.replace(Regex("[\\w.+-]+@[\\w.-]+\\.\\w+"), "<email>")
            .replace(Regex("https?://\\S+"), "<url>")
            .replace(Regex("\\b\\d{6,}\\b"), "<num>")
            .let { if (it.length > 300) it.substring(0, 300) else it }

    fun report(error: Throwable, where: String? = null) {
        if (!AppConfig.brokerAvailable) return
        val msg = scrub(error.toString())
        scope.launch {
            runCatching {
                Net.postJson(
                    "${AppConfig.brokerUrl}/log",
                    buildJsonObject {
                        put("level", JsonPrimitive("error"))
                        put("event", JsonPrimitive("client.error"))
                        put("surface", JsonPrimitive("native"))
                        put("message", JsonPrimitive(msg))
                        put("context", buildJsonObject {
                            put("type", JsonPrimitive(error::class.java.simpleName ?: "Throwable"))
                            if (where != null) put("where", JsonPrimitive(where))
                        })
                    },
                )
            } // telemetry must never throw
        }
    }

    /** Chain a global uncaught-exception handler that reports to the broker, then delegates. */
    fun install() {
        val prior = Thread.getDefaultUncaughtExceptionHandler()
        Thread.setDefaultUncaughtExceptionHandler { thread, throwable ->
            runCatching { report(throwable, where = "uncaught") }
            prior?.uncaughtException(thread, throwable)
        }
    }
}
