package org.membercovenantpath.viewer.ui.components

import android.annotation.SuppressLint
import android.webkit.CookieManager
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView

/**
 * Sign in on the Church's OWN web page, inside the app — so the password is autofilled (biometric-
 * unlocked) or typed ON churchofjesuschrist.org, never in our UI and never on our server. The full
 * Church MFA menu (text / email / authenticator) is available because it's the Church's own page.
 * When the login completes (the Church `appSession` cookies appear), we capture every
 * churchofjesuschrist.org cookie and hand it back; the caller posts it to the broker's
 * `/auth/session` capture endpoint, which verifies the session and mints/enrolls like the password
 * lane.
 *
 * True biometric/passkey AS AN MFA FACTOR can't run inside an embedded WebView (WebAuthn is blocked
 * there) — but biometric-unlocked password autofill + a texted/emailed/app code do, which is the
 * whole point: nothing secret touches our app.
 */
private const val LOGIN_URL = "https://lcr.churchofjesuschrist.org/api/auth/login"
private const val CHURCH_UA =
    "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) " +
        "Chrome/124.0.0.0 Mobile Safari/537.36"

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ChurchWebAuthSheet(
    isEnroll: Boolean,
    onCapture: (List<Map<String, String>>) -> Unit,
    onCancel: () -> Unit,
) {
    var loading by remember { mutableStateOf(true) }
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(if (isEnroll) "Authorize daily sync" else "Sign in") },
                navigationIcon = { TextButton(onClick = onCancel) { Text("Cancel") } },
                actions = {
                    Icon(Icons.Filled.Lock, contentDescription = null,
                        modifier = Modifier.padding(end = 4.dp))
                    Text("churchofjesuschrist.org", style = MaterialTheme.typography.labelSmall,
                        modifier = Modifier.padding(end = 12.dp))
                },
            )
        },
    ) { pad ->
        Box(Modifier.fillMaxSize().padding(pad)) {
            ChurchWebView(onCapture = onCapture, onLoadingChange = { loading = it })
            if (loading) {
                CircularProgressIndicator(Modifier.align(Alignment.Center))
            }
        }
    }
}

@SuppressLint("SetJavaScriptEnabled")
@Composable
private fun ChurchWebView(
    onCapture: (List<Map<String, String>>) -> Unit,
    onLoadingChange: (Boolean) -> Unit,
) {
    // Guard against double-firing once we've captured a session.
    var captured by remember { mutableStateOf(false) }
    AndroidView(factory = { ctx ->
        val cookieManager = CookieManager.getInstance()
        cookieManager.setAcceptCookie(true)
        WebView(ctx).apply {
            cookieManager.setAcceptThirdPartyCookies(this, true)
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            settings.userAgentString = CHURCH_UA
            webViewClient = object : WebViewClient() {
                override fun onPageStarted(view: WebView?, url: String?, favicon: android.graphics.Bitmap?) {
                    onLoadingChange(true)
                }

                override fun onPageFinished(view: WebView?, url: String?) {
                    onLoadingChange(false)
                    if (captured) return
                    // The Church login is done once the `appSession` cookies are set on lcr.*.
                    val lcr = cookieManager.getCookie("https://lcr.churchofjesuschrist.org") ?: ""
                    if (lcr.split(";").count { it.trim().startsWith("appSession") } < 2) return
                    captured = true
                    onCapture(collectChurchCookies(cookieManager))
                }
            }
            loadUrl(LOGIN_URL)
        }
    })
}

/**
 * Collect every churchofjesuschrist.org cookie the WebView holds (the Okta `sid` on id.* and the
 * LCR `appSession` on lcr.*), as {name,value,domain,path} maps for the broker. CookieManager returns
 * a "k=v; k2=v2" string per host (no domain/path), so we attach the parent domain — the broker sends
 * each cookie to whichever Church host needs it.
 */
private fun collectChurchCookies(cm: CookieManager): List<Map<String, String>> {
    val hosts = listOf(
        "https://lcr.churchofjesuschrist.org",
        "https://id.churchofjesuschrist.org",
        "https://churchofjesuschrist.org",
    )
    val out = LinkedHashMap<String, Map<String, String>>()
    for (host in hosts) {
        val raw = cm.getCookie(host) ?: continue
        for (pair in raw.split(";")) {
            val eq = pair.indexOf('=')
            if (eq <= 0) continue
            val name = pair.substring(0, eq).trim()
            val value = pair.substring(eq + 1).trim()
            if (name.isEmpty() || value.isEmpty()) continue
            // De-dupe by name; the parent domain makes the cookie valid for every Church host.
            out[name] = mapOf(
                "name" to name, "value" to value,
                "domain" to ".churchofjesuschrist.org", "path" to "/",
            )
        }
    }
    return out.values.toList()
}
