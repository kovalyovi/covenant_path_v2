#if canImport(UIKit)
import SwiftUI

/// In-app Church re-authorization (port of web `ReauthDialog` — feedback: "hit re-authorize and was
/// pushed back to the login screen — should be an extra modal"). Presents over the dashboard, runs
/// the Church sign-in WITH sync consent (enroll=true, MFA-aware: factor pick + code, single-factor
/// auto-select), and keeps the user in the app: on success the broker stores the fresh credential,
/// we adopt the re-minted Supabase session (same user — never the login screen), reload enrollment
/// status and toast. Used by the stale/revoked banner and the empty-state authorize CTAs.
struct ReauthSheet: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(\.appServices) private var services
    let store: DashboardStore
    let onToast: (String) -> Void

    enum Mode { case password, otp }

    @State private var mode: Mode = .password
    @State private var username = ""
    @State private var email = ""
    @State private var password = ""
    @State private var mfaCode = ""
    @State private var otpCode = ""
    @State private var loginID: String?
    @State private var factors: [BrokerFactor] = []
    @State private var factorSent: BrokerFactor?
    @State private var otpSent = false
    @State private var busy = false
    @State private var status: String?
    @State private var error: String?
    // Same MFA-input hygiene as LoginView (2026-06-11): codes never survive a factor switch or a
    // failed verify, and resend cools down so the member waits for the FRESH code.
    @State private var resendIn = 0
    @State private var resendTask: Task<Void, Never>?

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
    }

    // MARK: - the 3 steps (username/password → pick factor → enter code), mirrors web ReauthDialog

    @ViewBuilder
    private var stepContent: some View {
        if otpSent {
            Text("A code was just sent to your email. Enter it here.")
                .font(.callout)
            TextField("Verification code", text: $otpCode)
                .textContentType(.oneTimeCode).keyboardType(.numberPad)
                .textFieldStyle(.roundedBorder)
                .onChange(of: otpCode) { _, value in
                    let digits = String(value.filter(\.isNumber).prefix(8))
                    if digits != value { otpCode = digits }
                }
            primaryButton("Verify & authorize", disabled: otpCode.count < 6) { try await verifyOtp() }
            Button(resendIn > 0 ? "Send a new code (\(resendIn)s)" : "Send a new code") {
                run { try await startOtp() }
            }
            .disabled(busy || resendIn > 0)
            Button("Use a different email") {
                otpSent = false
                otpCode = ""
                resendIn = 0
            }
            .disabled(busy)
        } else if let factorSent {
            // The prompt names the code's SOURCE (texted to the masked number vs authenticator
            // app) — a right-looking code from the wrong source is the multi-method trap.
            let tips = mfaPrompt(for: factorSent)
            Text(tips.prompt).font(.callout)
            if let warning = tips.warning {
                Text(warning).font(.caption).foregroundStyle(.tint)
            }
            TextField("Verification code", text: $mfaCode)
                .textContentType(.oneTimeCode).keyboardType(.numberPad)
                .textFieldStyle(.roundedBorder)
                .onChange(of: mfaCode) { _, value in
                    let digits = String(value.filter(\.isNumber).prefix(8))
                    if digits != value { mfaCode = digits }
                }
            primaryButton("Verify & authorize", disabled: mfaCode.count < 6) { try await verify() }
            Button(resendIn > 0 ? "Send a new code (\(resendIn)s)" : "Send a new code") {
                run { try await pickFactor(factorSent) }
            }
            .disabled(busy || resendIn > 0)
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
                    .buttonStyle(.bordered).frame(maxWidth: .infinity)
                    .disabled(busy)
            }
        } else {
            Text("Sign in with your Church account (same as LCR) to re-authorize the daily sync. "
                 + "The session is stored encrypted — never your password — and is revocable anytime.")
                .font(.callout).foregroundStyle(.secondary)
            Picker("Sign-in method", selection: $mode) {
                Text("Church username").tag(Mode.password)
                Text("Email code").tag(Mode.otp)
            }
            .pickerStyle(.segmented)
            .disabled(busy)
            .padding(.bottom, 8)
            if case .password = mode {
                TextField("Church username", text: $username)
                    .textContentType(.username).textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .textFieldStyle(.roundedBorder)
                SecureField("Password", text: $password)
                    .textContentType(.password)
                    .submitLabel(.go).onSubmit { if !busy, !username.trimmed.isEmpty, !password.isEmpty { run { try await signIn() } } }
                    .textFieldStyle(.roundedBorder)
                primaryButton("Authorize", disabled: username.trimmed.isEmpty || password.isEmpty) { try await signIn() }
            } else if case .otp = mode {
                TextField("Church email", text: $email)
                    .textContentType(.emailAddress)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .keyboardType(.emailAddress)
                    .textFieldStyle(.roundedBorder)
                    .onSubmit { if !busy, !email.trimmed.isEmpty { run { try await startOtp() } } }
                primaryButton("Send code", disabled: email.trimmed.isEmpty) { try await startOtp() }
            }
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
        .buttonStyle(.borderedProminent)
        .disabled(busy || disabled)
    }

    // MARK: - flow (enroll=true on every auth call: this IS the consent)

    private var broker: BrokerService? { services?.broker }

    private func signIn() async throws {
        guard let broker else { throw BrokerError("Church login is not configured (BROKER_URL).") }
        let r = try await broker.password(username.trimmed, password, enroll: true)
        if r.mfaRequired {
            loginID = r.loginID
            factors = r.factors
            // Auto-send if there's exactly one factor (matches the login flow + web).
            if r.factors.count == 1, let id = r.loginID {
                try await broker.selectFactor(loginID: id, factorID: r.factors[0].id)
                factorSent = r.factors[0]
                mfaCode = ""
                startResendCooldown()
            }
            return
        }
        try await finish(r)
    }

    private func startOtp() async throws {
        guard let broker else { throw BrokerError("Church login is not configured (BROKER_URL).") }
        try await broker.otpStart(email.trimmed, enroll: true)
        otpSent = true
        otpCode = ""
        startResendCooldown()
    }

    private func verifyOtp() async throws {
        guard let broker else { return }
        do {
            let r = try await broker.otpVerify(email.trimmed, otpCode.trimmed, enroll: true)
            try await finish(r)
        } catch {
            otpCode = "" // a rejected code must be retyped fresh, not resubmitted stale
            throw error
        }
    }

    private func pickFactor(_ f: BrokerFactor) async throws {
        guard let broker, let loginID else { return }
        try await broker.selectFactor(loginID: loginID, factorID: f.id)
        factorSent = f
        mfaCode = ""
        startResendCooldown()
    }

    private func verify() async throws {
        guard let broker, let loginID else { return }
        do {
            let r = try await broker.verifyMfa(loginID: loginID, code: mfaCode.trimmed, enroll: true)
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
