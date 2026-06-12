#if canImport(UIKit)
import SwiftUI
import WebKit

/// Sign in on the Church's OWN web page, inside the app — so the password is autofilled (Face-ID
/// unlocked keychain) or typed ON churchofjesuschrist.org, never in our UI and never on our server.
/// The full Church MFA menu (text / email / authenticator) is available because it's the Church's
/// own page. When the login completes (the Church `appSession` cookies appear on lcr.*), we capture
/// every churchofjesuschrist.org cookie and hand it back; `SessionStore` posts it to the broker's
/// `/auth/session` capture endpoint, which verifies the session and mints/enrolls exactly like the
/// password lane.
///
/// True Face ID / passkey AS AN MFA FACTOR can't run inside an embedded WebView (Apple blocks
/// WebAuthn there) — but keychain password autofill (Face-ID gated) + a texted/emailed/app code do,
/// which is the whole point: nothing secret touches our app.
struct ChurchWebAuthSheet: View {
    /// What the leader is doing — only affects the title/subtitle copy.
    enum Purpose { case login, enroll }

    let purpose: Purpose
    let onCapture: ([[String: String]]) -> Void
    let onCancel: () -> Void

    @State private var loading = true

    var body: some View {
        NavigationStack {
            ZStack {
                ChurchWebView(loading: $loading, onCapture: onCapture)
                if loading {
                    ProgressView("Loading the Church sign-in…")
                        .padding()
                        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 12))
                }
            }
            .ignoresSafeArea(edges: .bottom)
            .navigationTitle(purpose == .enroll ? "Authorize daily sync" : "Sign in")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Cancel") { onCancel() }
                }
                ToolbarItem(placement: .principal) {
                    // Reassures the leader WHERE they are — this is the real Church page.
                    Label("churchofjesuschrist.org", systemImage: "lock.fill")
                        .font(.caption).foregroundStyle(.secondary)
                        .labelStyle(.titleAndIcon)
                }
            }
        }
    }
}

/// The WKWebView itself: loads the Church OAuth login, watches for the post-login `appSession`
/// cookies, and captures every churchofjesuschrist.org cookie on success.
private struct ChurchWebView: UIViewRepresentable {
    @Binding var loading: Bool
    let onCapture: ([[String: String]]) -> Void

    /// LCR's OAuth login initiator — 302s to the Church Okta sign-in, then back to lcr.* with the
    /// `appSession` cookies once auth (incl. any MFA) completes. Matches the proven Mission-KPIs flow.
    static let loginURL = URL(string: "https://lcr.churchofjesuschrist.org/api/auth/login")!

    func makeCoordinator() -> Coordinator { Coordinator(loading: $loading, onCapture: onCapture) }

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        // A FRESH, non-persistent session every time: no stale Church SSO is silently captured, the
        // leader does a real sign-in (password autofill from the keychain still works — that's OS
        // keychain, not cookies), and nothing lingers in a shared cookie jar afterwards.
        config.websiteDataStore = .nonPersistent()
        let webView = WKWebView(frame: .zero, configuration: config)
        webView.navigationDelegate = context.coordinator
        webView.allowsBackForwardNavigationGestures = true
        // Match the UA the rest of the app uses for Church traffic (Akamai fingerprints it).
        webView.customUserAgent =
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
            + "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
        webView.load(URLRequest(url: Self.loginURL))
        return webView
    }

    func updateUIView(_ webView: WKWebView, context: Context) {}

    final class Coordinator: NSObject, WKNavigationDelegate {
        private let loading: Binding<Bool>
        private let onCapture: ([[String: String]]) -> Void
        private var captured = false

        init(loading: Binding<Bool>, onCapture: @escaping ([[String: String]]) -> Void) {
            self.loading = loading
            self.onCapture = onCapture
        }

        func webView(_ webView: WKWebView, didStartProvisionalNavigation navigation: WKNavigation!) {
            loading.wrappedValue = true
        }

        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            loading.wrappedValue = false
            checkForSession(webView)
        }

        func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!,
                     withError error: Error) {
            loading.wrappedValue = false
        }

        /// The Church login is done once both `appSession.0` and `appSession.1` are set on the
        /// Church domain (the success signal from the LCR OAuth callback). Capture every
        /// churchofjesuschrist.org cookie (Okta `sid` + LCR `appSession`) so the broker can verify
        /// whichever it needs.
        private func checkForSession(_ webView: WKWebView) {
            guard !captured else { return }
            webView.configuration.websiteDataStore.httpCookieStore.getAllCookies { [weak self] cookies in
                guard let self, !self.captured else { return }
                let church = cookies.filter { $0.domain.contains("churchofjesuschrist.org") }
                let appSession = church.filter { $0.name.hasPrefix("appSession") }
                guard appSession.count >= 2 else { return }  // not done yet — still mid-login
                self.captured = true
                let payload: [[String: String]] = church.map {
                    ["name": $0.name, "value": $0.value, "domain": $0.domain, "path": $0.path]
                }
                self.onCapture(payload)
            }
        }
    }
}
#endif
