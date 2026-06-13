#if canImport(UIKit)
import SwiftUI

/// Two ways in, one resulting session (plus passkey where supported). Faithful port of
/// `login_page.dart`: a Church-account ↔ Email-code segmented control (only when the broker is
/// configured), the MFA factor pick + code steps, the email-code flow with a broker-relay fallback,
/// the "Sign in with a passkey" button, and the disclaimer text + footer.
struct LoginView: View {
    @Environment(SessionStore.self) private var session

    @State private var username = ""
    @State private var password = ""
    @State private var mfaCode = ""
    @State private var email = ""
    @State private var emailCode = ""
    // "Send a new code" cooldown — nudges the member to wait for the FRESH code instead of typing
    // one from an earlier text/screen (a stale code submitted seconds after the send is exactly
    // what stranded a stake leader at MFA, 2026-06-11).
    @State private var resendIn = 0
    @State private var resendTask: Task<Void, Never>?
    @FocusState private var focused: Field?

    enum Field { case username, password, mfa, email, code }

    /// Mid-MFA the screen shows ONE flow: the mode picker and passkey button hide (a member stuck
    /// on the code screen reached for the passkey button — a silent dead-end, 2026-06-11).
    private var inMfa: Bool {
        session.mode == .church && session.brokerAvailable && session.loginID != nil
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                Text("Covenant Path").font(.largeTitle.bold())

                if session.brokerAvailable && !inMfa {
                    Picker("Mode", selection: modeBinding) {
                        ForEach(SessionStore.Mode.allCases, id: \.self) { m in
                            Text(m.label).tag(m)
                        }
                    }
                    .pickerStyle(.segmented)
                    .disabled(session.isBusy)
                }

                if session.mode == .church && session.brokerAvailable {
                    churchFields
                } else {
                    emailFields
                }

                if session.passkeyAvailable && !inMfa {
                    HStack {
                        VStack { Divider() }
                        Text("or").font(.footnote).foregroundStyle(.secondary)
                        VStack { Divider() }
                    }
                    Button {
                        Task { await session.passkeySignIn() }
                    } label: {
                        Label("Sign in with a passkey", systemImage: "person.badge.key")
                            .frame(maxWidth: .infinity)
                    }
                    .cpGlassButton()
                    .disabled(session.isBusy)
                } else if session.brokerAvailable && !inMfa {
                    // Documented partial: native passkeys need an associated-domains entitlement +
                    // a configured RP id. Until then, the button is shown disabled with a note.
                    VStack(alignment: .leading, spacing: 4) {
                        Button {} label: {
                            Label("Sign in with a passkey", systemImage: "person.badge.key")
                                .frame(maxWidth: .infinity)
                        }
                        .cpGlassButton()
                        .disabled(true)
                        Text("Passkeys aren't set up on this build — use an email code on this device.")
                            .font(.caption2).foregroundStyle(.secondary)
                    }
                }

                if session.isBusy, let status = session.statusMessage {
                    Text(status).font(.callout).foregroundStyle(.tint)
                }
                if let error = session.errorMessage {
                    Text(error).font(.callout).foregroundStyle(.red)
                }
            }
            .padding(24)
            .frame(maxWidth: 420, alignment: .leading)
            .frame(maxWidth: .infinity)
        }
        .scrollDismissesKeyboard(.interactively)
        // Input typed for the OLD factor must never ride into a new challenge (2026-06-11); a
        // fresh send also (re)starts the resend cooldown. Covers auto-select and manual picks.
        .onChange(of: session.factorSent?.id) { _, newValue in
            mfaCode = ""
            if newValue != nil {
                startResendCooldown()
            } else {
                resendTask?.cancel()
                resendIn = 0
            }
        }
        // "Sign in on the Church website" — the WebView capture lane (no password in our app).
        .sheet(isPresented: Binding(get: { session.showChurchWebLogin },
                                    set: { session.showChurchWebLogin = $0 })) {
            ChurchWebAuthSheet(
                purpose: .login,
                onCapture: { cookies in Task { await session.churchWebLogin(cookies: cookies) } },
                onCancel: { session.showChurchWebLogin = false })
        }
        // #8: post-login offer to set up / improve daily sync (consent moved off the login form).
        .alert(session.enrollOffer?.improving == true ? "Improve your stake's sync?" : "Set up daily sync?",
               isPresented: enrollOfferBinding, presenting: session.enrollOffer) { _ in
            Button(session.enrollOffer?.improving == true ? "Authorize sync" : "Set up sync") {
                Task { await session.confirmEnroll() }
            }
            Button("Not now", role: .cancel) { Task { await session.declineEnroll() } }
        } message: { offer in
            Text(offer.improving
                 ? "\(offer.stake) is currently synced by a leader whose access can't pull everything. "
                   + "Authorize your Church session to take over the daily sync? It's stored encrypted "
                   + "(never your password) and revocable anytime in Settings."
                 : "\(offer.stake) isn't set up for daily sync yet. Authorize your Church session so your "
                   + "stake's data refreshes automatically each day? It's stored encrypted (never your "
                   + "password) and revocable anytime in Settings.")
        }
    }

    private var enrollOfferBinding: Binding<Bool> {
        Binding(get: { session.enrollOffer != nil },
                set: { if !$0 && session.enrollOffer != nil { Task { await session.declineEnroll() } } })
    }

    private var modeBinding: Binding<SessionStore.Mode> {
        Binding(get: { session.mode }, set: { session.selectMode($0) })
    }

    // MARK: - Church fields (3 steps: username/password → pick factor → enter code)

    @ViewBuilder
    private var churchFields: some View {
        if let factor = session.factorSent {
            // Step 3: enter the MFA code (digits only, gated on a complete code — fat-finger and
            // stale submits 401 and restart the dance). The prompt names the code's SOURCE — a
            // right-looking code from the wrong source is the multi-method trap (2026-06-11).
            let tips = mfaPrompt(for: factor)
            Text(tips.prompt).font(.callout)
            if let warning = tips.warning {
                Text(warning).font(.caption).foregroundStyle(.tint)
            }
            TextField("Verification code", text: $mfaCode)
                .textContentType(.oneTimeCode).keyboardType(.numberPad)
                .focused($focused, equals: .mfa)
                .textFieldStyle(.roundedBorder)
                .onChange(of: mfaCode) { _, value in
                    let digits = String(value.filter(\.isNumber).prefix(8))
                    if digits != value { mfaCode = digits }
                }
            primaryButton("Verify & sign in", disabledWhen: mfaCode.count < 6) {
                await session.verifyMfa(code: mfaCode)
                if session.errorMessage != nil { mfaCode = "" } // a rejected code must be retyped fresh
            }
            Button(resendIn > 0 ? "Send a new code (\(resendIn)s)" : "Send a new code") {
                Task {
                    await session.selectFactor(factor)
                    startResendCooldown()
                }
            }
            .disabled(session.isBusy || resendIn > 0)
            if let hint = tips.noCodeHint {
                Text(hint).font(.caption).foregroundStyle(.secondary)
            }
            Button("Choose a different method") { session.backFromMfa() }.disabled(session.isBusy)
            Button("Start over") { session.backToChurchStart() }.disabled(session.isBusy)
        } else if session.loginID != nil {
            // Step 2: pick a factor.
            Text("Choose how to receive your verification code:").font(.callout)
            ForEach(session.factors) { f in
                Button(f.label) { Task { await session.selectFactor(f) } }
                    .cpGlassButton().frame(maxWidth: .infinity)
                    .disabled(session.isBusy)
            }
            Button("Start over") { session.backToChurchStart() }.disabled(session.isBusy)
        } else {
            // Step 1: username + password.
            Text("Sign in with your Church account (same as LCR).").font(.callout)
            TextField("Church username", text: $username)
                .textContentType(.username).textInputAutocapitalization(.never)
                .autocorrectionDisabled().focused($focused, equals: .username)
                .textFieldStyle(.roundedBorder)
            SecureField("Password", text: $password)
                .textContentType(.password).focused($focused, equals: .password)
                .submitLabel(.go).onSubmit(churchSignIn)
                .textFieldStyle(.roundedBorder)
            // No "authorize daily sync" toggle here (#8): signing in only views. If the stake isn't
            // synced yet, we offer to set it up in an alert AFTER a successful sign-in.
            primaryButton("Sign in") {
                await session.churchSignIn(username: username, password: password)
            }
            // Prefer not to type a password here? Sign in on the Church's own page in a WebView —
            // the password is autofilled (Face ID) / typed on churchofjesuschrist.org, never in our
            // app, with the full Church MFA. The captured session is what reaches the broker.
            Button {
                session.presentChurchWebLogin()
            } label: {
                Label("Sign in on the Church website instead", systemImage: "globe")
                    .frame(maxWidth: .infinity)
            }
            .cpGlassButton()
            .disabled(session.isBusy)
            Text("Opens churchofjesuschrist.org — your password is entered there, never in this app.")
                .font(.caption2).foregroundStyle(.secondary)
        }
    }

    private func churchSignIn() {
        focused = nil
        Task { await session.churchSignIn(username: username, password: password) }
    }

    // MARK: - Email fields (+ relay fallback)

    @ViewBuilder
    private var emailFields: some View {
        Text("Sign in with the email your stake has on file.").font(.callout)
        if session.useRelay {
            HStack(alignment: .top, spacing: 6) {
                Image(systemName: "shield").font(.caption).foregroundStyle(.tint)
                Text("Backup mode: signing in through our server (for networks that block Supabase).")
                    .font(.caption).foregroundStyle(.tint)
            }
        }
        TextField("Email", text: $email)
            .textContentType(.emailAddress).keyboardType(.emailAddress)
            .textInputAutocapitalization(.never).autocorrectionDisabled()
            .disabled(session.emailCodeSent)
            .focused($focused, equals: .email)
            .textFieldStyle(.roundedBorder)
        if session.emailCodeSent {
            TextField("6-digit code", text: $emailCode)
                .textContentType(.oneTimeCode).keyboardType(.numberPad)
                .focused($focused, equals: .code)
                .textFieldStyle(.roundedBorder)
        }
        primaryButton(session.emailCodeSent ? "Verify & sign in" : "Send code") {
            if session.emailCodeSent { await session.verify(email: email, code: emailCode) }
            else { await session.sendCode(email: email) }
        }
        if session.emailCodeSent {
            Button("Use a different email") { session.resetEmailEntry() }.disabled(session.isBusy)
        }
        if session.brokerAvailable && !session.useRelay {
            Button("Can't connect? Use backup sign-in") { session.enableRelay() }
                .disabled(session.isBusy)
        }
        if session.useRelay {
            Button("Use normal sign-in") { session.disableRelay() }.disabled(session.isBusy)
        }
    }

    // MARK: - resend cooldown

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

    // MARK: - shared button

    @ViewBuilder
    private func primaryButton(_ title: String, disabledWhen: Bool = false,
                               action: @escaping () async -> Void) -> some View {
        Button {
            focused = nil
            Task { await action() }
        } label: {
            if session.isBusy {
                ProgressView().frame(maxWidth: .infinity).controlSize(.small)
            } else {
                Text(title).frame(maxWidth: .infinity)
            }
        }
        .cpGlassButton(prominent: true)
        .disabled(session.isBusy || disabledWhen)
    }
}
#endif
