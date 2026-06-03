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
    // Explicit, default-OFF authorization — signing in alone never captures the leader's session.
    @State private var authorizeSync = false
    @FocusState private var focused: Field?

    enum Field { case username, password, mfa, email, code }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                Text("Covenant Path").font(.largeTitle.bold())

                if session.brokerAvailable {
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

                if session.passkeyAvailable {
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
                    .buttonStyle(.bordered)
                    .disabled(session.isBusy)
                } else if session.brokerAvailable {
                    // Documented partial: native passkeys need an associated-domains entitlement +
                    // a configured RP id. Until then, the button is shown disabled with a note.
                    VStack(alignment: .leading, spacing: 4) {
                        Button {} label: {
                            Label("Sign in with a passkey", systemImage: "person.badge.key")
                                .frame(maxWidth: .infinity)
                        }
                        .buttonStyle(.bordered)
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
    }

    private var modeBinding: Binding<SessionStore.Mode> {
        Binding(get: { session.mode }, set: { session.selectMode($0) })
    }

    // MARK: - Church fields (3 steps: username/password → pick factor → enter code)

    @ViewBuilder
    private var churchFields: some View {
        if session.factorSent != nil {
            // Step 3: enter the MFA code.
            Text("Enter the code sent via \(session.factorSent?.label ?? "your method").").font(.callout)
            TextField("Verification code", text: $mfaCode)
                .textContentType(.oneTimeCode).keyboardType(.numberPad)
                .focused($focused, equals: .mfa)
                .textFieldStyle(.roundedBorder)
            primaryButton("Verify & sign in") { await session.verifyMfa(code: mfaCode) }
            Button("Choose a different method") { session.backFromMfa() }.disabled(session.isBusy)
        } else if session.loginID != nil {
            // Step 2: pick a factor.
            Text("Choose how to receive your verification code:").font(.callout)
            ForEach(session.factors) { f in
                Button(f.label) { Task { await session.selectFactor(f) } }
                    .buttonStyle(.bordered).frame(maxWidth: .infinity)
                    .disabled(session.isBusy)
            }
            Button("Back") { session.backToChurchStart() }.disabled(session.isBusy)
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
            Toggle(isOn: $authorizeSync) {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Authorize daily sync for my stake").font(.callout)
                    Text("Stores this Church session (encrypted — never your password) so your stake's "
                         + "data refreshes daily. Optional — leave it off to just view. Revoke anytime "
                         + "in Settings.")
                        .font(.caption).foregroundStyle(.secondary)
                }
            }
            .disabled(session.isBusy)
            primaryButton("Sign in") {
                await session.churchSignIn(username: username, password: password, authorizeSync: authorizeSync)
            }
        }
    }

    private func churchSignIn() {
        focused = nil
        Task { await session.churchSignIn(username: username, password: password, authorizeSync: authorizeSync) }
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

    // MARK: - shared button

    @ViewBuilder
    private func primaryButton(_ title: String, action: @escaping () async -> Void) -> some View {
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
        .buttonStyle(.borderedProminent)
        .disabled(session.isBusy)
    }
}
#endif
