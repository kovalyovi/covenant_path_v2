#if canImport(UIKit)
import SwiftUI

/// In-app Church re-authorization (port of web `ReauthDialog` — feedback: "hit re-authorize and was
/// pushed back to the login screen — should be an extra modal"). Presents over the dashboard, runs
/// the Church sign-in WITH sync consent (enroll=true, MFA-aware: factor pick + code, single-factor
/// auto-select), and keeps the user in the app: on success the broker stores the fresh credential,
/// we adopt the re-minted Supabase session (same user — never the login screen), reload enrollment
/// status and toast. Used by the stale/revoked banner and the empty-state authorize CTAs.
///
/// USERNAME + PASSWORD ONLY (2026-06-12). Setting up daily sync mints a 45-day Member Tools token via
/// a silent SSO that needs the global Okta session only the classic username+password lane establishes
/// (/auth/web/*). The passwordless emailed-code (OTP) lane was removed: its Okta session is app-scoped
/// and could never mint the token. A leader who'd rather not type a password uses the Church-website
/// capture below (also enroll=true). See docs/DECISIONS.md (ADR-011).
struct ReauthSheet: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(\.appServices) private var services
    let store: DashboardStore
    let onToast: (String) -> Void

    @State private var username = ""
    @State private var password = ""
    @State private var mfaCode = ""
    @State private var loginID: String?
    @State private var factors: [BrokerFactor] = []
    @State private var factorSent: BrokerFactor?
    @State private var busy = false
    @State private var status: String?
    @State private var error: String?
    // Same MFA-input hygiene as LoginView (2026-06-11): codes never survive a factor switch or a
    // failed verify, and resend cools down so the member waits for the FRESH code.
    @State private var resendIn = 0
    @State private var resendTask: Task<Void, Never>?
    @State private var showChurchWeb = false

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    stepContent
                    if busy, let status {
                        Text(status).font(.callout).foregroundStyle(.tint)
                    }
                    if let error {
                        Text(error).font(.callout).foregroundStyle(.red)
                    }
                }
                .padding(20)
                .frame(maxWidth: 420, alignment: .leading)
                .frame(maxWidth: .infinity)
            }
            .navigationTitle("Re-authorize daily sync")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Cancel") { dismiss() }.disabled(busy)
                }
            }
        }
        .presentationDetents([.medium, .large])
        .interactiveDismissDisabled(busy)
        .sheet(isPresented: $showChurchWeb) {
            ChurchWebAuthSheet(
                purpose: .enroll,
                onCapture: { cookies in showChurchWeb = false; authorizeWithCaptured(cookies) },
                onCancel: { showChurchWeb = false })
        }
    }

    // MARK: - the 3 steps (username/password → pick factor → enter code), mirrors web ReauthDialog

    @ViewBuilder
    private var stepContent: some View {
        if let factorSent {
            // The prompt names the code's SOURCE (texted to the masked number vs authenticator
            // app) — a right-looking code from the wrong source is the multi-method trap.
            let tips = mfaPrompt(for: factorSent)
            let isPassword = factorSent.method == "password"
            Text(tips.prompt).font(.callout)
            if let warning = tips.warning {
                Text(warning).font(.caption).foregroundStyle(.tint)
            }
            if isPassword {
                // MFA continuation: the next factor is the PASSWORD (a distinct factor type from a
                // code) — not a 6-digit code.
                SecureField("Password", text: $mfaCode)
                    .textContentType(.password)
                    .textFieldStyle(.roundedBorder)
            } else {
                TextField("Verification code", text: $mfaCode)
                    .textContentType(.oneTimeCode).keyboardType(.numberPad)
                    .textFieldStyle(.roundedBorder)
                    .onChange(of: mfaCode) { _, value in
                        let digits = String(value.filter(\.isNumber).prefix(8))
                        if digits != value { mfaCode = digits }
                    }
            }
            primaryButton("Verify & authorize",
                          disabled: isPassword ? mfaCode.isEmpty : mfaCode.count < 6) { try await verify() }
            if !isPassword {
                Button(resendIn > 0 ? "Send a new code (\(resendIn)s)" : "Send a new code") {
                    run { try await pickFactor(factorSent) }
                }
                .disabled(busy || resendIn > 0)
            }
            if let hint = tips.noCodeHint {
                Text(hint).font(.caption).foregroundStyle(.secondary)
            }
            Button("Choose a different method") {
                self.factorSent = nil
                mfaCode = ""
            }
            .disabled(busy)
        } else if loginID != nil {
            Text("Choose how to receive your verification code:").font(.callout)
            ForEach(factors) { f in
                Button(f.label) { run { try await pickFactor(f) } }
                    .cpGlassButton().frame(maxWidth: .infinity)
                    .disabled(busy)
            }
        } else {
            Text("Sign in with your Church account (same username and password as LCR) to set up the "
                 + "daily sync. The session is stored encrypted — never your password — and is "
                 + "revocable anytime.")
                .font(.callout).foregroundStyle(.secondary)
            Text("Daily sync needs your username and password — that's the only sign-in the Church "
                 + "lets us renew unattended for ~45 days. (An emailed code can sign you in to view, "
                 + "but can't authorize the background sync.)")
                .font(.caption).foregroundStyle(.secondary)
            TextField("Church username", text: $username)
                .textContentType(.username).textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .textFieldStyle(.roundedBorder)
            SecureField("Password", text: $password)
                .textContentType(.password)
                .submitLabel(.go).onSubmit { if !busy, !username.trimmed.isEmpty, !password.isEmpty { run { try await signIn() } } }
                .textFieldStyle(.roundedBorder)
            primaryButton("Authorize", disabled: username.trimmed.isEmpty || password.isEmpty) { try await signIn() }
            // No password in our app: authorize by signing in on the Church's own web page. Best
            // for an MFA-enabled account (the full Church MFA is available there).
            Divider().padding(.vertical, 4)
            Button {
                error = nil
                showChurchWeb = true
            } label: {
                Label("Authorize on the Church website instead", systemImage: "globe")
                    .frame(maxWidth: .infinity)
            }
            .cpGlassButton()
            .disabled(busy)
            Text("Opens churchofjesuschrist.org — your password is entered there, never in this app.")
                .font(.caption2).foregroundStyle(.secondary)
        }
    }

    /// The Church web sheet captured a session (the leader authorized on churchofjesuschrist.org).
    /// Post the cookies with enroll=true so the broker stores the sync credential, then finish.
    private func authorizeWithCaptured(_ cookies: [[String: String]]) {
        guard let broker = services?.broker else { return }
        run {
            let r = try await broker.captureSession(cookies: cookies, enroll: true)
            try await finish(r)
        }
    }

    @ViewBuilder
    private func primaryButton(_ title: String, disabled: Bool, action: @escaping () async throws -> Void) -> some View {
        Button {
            run { try await action() }
        } label: {
            if busy {
                ProgressView().frame(maxWidth: .infinity).controlSize(.small)
            } else {
                Text(title).frame(maxWidth: .infinity)
            }
        }
        .cpGlassButton(prominent: true)
        .disabled(busy || disabled)
    }

    // MARK: - flow (enroll=true on every auth call: this IS the consent)

    private var broker: BrokerService? { services?.broker }

    private func signIn() async throws {
        guard let broker else { throw BrokerError("Church login is not configured (BROKER_URL).") }
        // The password lane IS the credential-capture (one-MFA) flow (/auth/web/*): the single MFA
        // mints the 45-day sync token.
        let r = try await broker.webStart(username.trimmed, password, enroll: true)
        if r.mfaRequired {
            try await enterMfa(r)
            return
        }
        try await finish(r)
    }

    /// Enter (or re-enter) the MFA factor step. An MFA-enabled account may, after the first factor,
    /// demand a DISTINCT factor (for Church accounts sometimes the password, 2026-06-12).
    private func enterMfa(_ r: BrokerResult) async throws {
        guard let broker else { return }
        loginID = r.loginID
        factors = r.factors
        factorSent = nil
        mfaCode = ""
        // Auto-send if there's exactly one factor (matches the login flow + web).
        if r.factors.count == 1, let id = r.loginID {
            try await broker.webSelectFactor(loginID: id, factorID: r.factors[0].id)
            factorSent = r.factors[0]
            startResendCooldown()
        }
    }

    private func pickFactor(_ f: BrokerFactor) async throws {
        guard let broker, let loginID else { return }
        try await broker.webSelectFactor(loginID: loginID, factorID: f.id)
        factorSent = f
        mfaCode = ""
        startResendCooldown()
    }

    private func verify() async throws {
        guard let broker, let loginID else { return }
        do {
            let r = try await broker.webVerify(loginID: loginID, code: mfaCode.trimmed, enroll: true)
            if r.mfaRequired {
                try await enterMfa(r) // chained continuation (rare): yet another factor owed
                return
            }
            try await finish(r)
        } catch {
            mfaCode = "" // a rejected code must be retyped fresh, not resubmitted stale
            throw error
        }
    }

    private func startResendCooldown() {
        resendTask?.cancel()
        resendIn = 30
        resendTask = Task { @MainActor in
            while resendIn > 0 && !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 1_000_000_000)
                if Task.isCancelled { return }
                resendIn -= 1
            }
        }
    }

    private func finish(_ r: BrokerResult) async throws {
        if r.authorized == false { throw BrokerError(SessionStore.noAccessMessage) }
        // Adopt the freshly-minted session (same user — keeps them signed in, never the login screen).
        if let email = r.email, let otp = r.otp, let services {
            try await services.auth.consume(email: email, otp: otp)
        }
        onToast(r.stored
                ? "Daily sync authorized — your stake will refresh within minutes."
                : "Signed in — sync authorization completed.")
        await store.loadEnrollStatus()
        dismiss()
    }

    /// Busy/error bookkeeping + the web's 5s "this can take a minute" progress note (a first-enroll
    /// login runs the broker's access evaluation server-side, legitimately 30–60s).
    private func run(_ action: @escaping () async throws -> Void) {
        busy = true
        error = nil
        let stage = Task {
            try? await Task.sleep(nanoseconds: 5_000_000_000)
            if !Task.isCancelled {
                status = "Authorizing — checking what your calling can access (up to a minute)…"
            }
        }
        Task {
            do {
                try await action()
            } catch let e as BrokerError {
                error = e.message
            } catch let e {
                error = e.localizedDescription
            }
            stage.cancel()
            status = nil
            busy = false
        }
    }
}
#endif
