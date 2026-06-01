#if canImport(UIKit)
import SwiftUI

/// Email-OTP login (the only login in the PoC). Step 1: enter email → "Send code". Step 2: enter the
/// 6-digit code Supabase emailed → "Verify & sign in". RLS scopes everything to the verified email.
/// Mirrors the email-code half of the Flutter `login_page.dart`.
struct LoginView: View {
    @Environment(SessionStore.self) private var session

    @State private var email = ""
    @State private var code = ""
    @FocusState private var focused: Field?

    enum Field { case email, code }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                Text("Covenant Path").font(.largeTitle.bold())
                Text("A read-only dashboard for stake and ward leaders tracking new-member "
                     + "integration. Sign in with the email your stake has on file.")
                    .font(.callout).foregroundStyle(.secondary)

                Spacer().frame(height: 8)

                if !session.codeSent {
                    emailStep
                } else {
                    codeStep
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

    // MARK: - steps

    private var emailStep: some View {
        VStack(alignment: .leading, spacing: 16) {
            TextField("Email", text: $email)
                .textContentType(.emailAddress)
                .keyboardType(.emailAddress)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .focused($focused, equals: .email)
                .submitLabel(.send)
                .onSubmit(send)
                .textFieldStyle(.roundedBorder)

            Button(action: send) {
                buttonLabel("Send code")
            }
            .buttonStyle(.borderedProminent)
            .disabled(session.isBusy)
        }
        .onAppear { focused = .email }
    }

    private var codeStep: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("Enter the 6-digit code sent to \(email).").font(.callout)
            TextField("6-digit code", text: $code)
                .textContentType(.oneTimeCode)
                .keyboardType(.numberPad)
                .focused($focused, equals: .code)
                .textFieldStyle(.roundedBorder)

            Button(action: verify) {
                buttonLabel("Verify & sign in")
            }
            .buttonStyle(.borderedProminent)
            .disabled(session.isBusy)

            Button("Use a different email") {
                code = ""
                session.resetEmailEntry()
            }
            .disabled(session.isBusy)
        }
        .onAppear { focused = .code }
    }

    @ViewBuilder
    private func buttonLabel(_ title: String) -> some View {
        if session.isBusy {
            ProgressView().frame(maxWidth: .infinity).controlSize(.small)
        } else {
            Text(title).frame(maxWidth: .infinity)
        }
    }

    // MARK: - actions

    private func send() {
        focused = nil
        Task { await session.sendCode(email: email) }
    }

    private func verify() {
        focused = nil
        Task { await session.verify(email: email, code: code) }
    }
}
#endif
