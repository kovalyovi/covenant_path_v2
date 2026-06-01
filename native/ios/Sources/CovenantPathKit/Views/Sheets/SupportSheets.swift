#if canImport(UIKit)
import SwiftUI

/// Contact support (port of `_contactSupport`): subject + message → broker `/contact`.
struct ContactSupportSheet: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(\.appServices) private var services
    let onToast: (String) -> Void

    @State private var subject = ""
    @State private var message = ""
    @State private var busy = false

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Text("Send a message to the app owner. They'll reply to your sign-in email.")
                        .font(.footnote).foregroundStyle(.secondary)
                }
                Section {
                    TextField("Subject (optional)", text: $subject)
                    TextField("How can we help?", text: $message, axis: .vertical)
                        .lineLimit(3...6)
                }
            }
            .navigationTitle("Contact support")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Send") { Task { await send() } }
                        .disabled(busy || message.trimmingCharacters(in: .whitespaces).isEmpty)
                }
            }
        }
        .presentationDetents([.medium, .large])
    }

    private func send() async {
        guard let broker = services?.broker else { return }
        busy = true
        do {
            try await broker.contact(subject: subject.trimmed, message: message.trimmed)
            dismiss(); onToast("Message sent — thank you!")
        } catch { onToast("Couldn't send: \(error.localizedDescription)") }
        busy = false
    }
}

/// Send feedback (port of `_sendFeedback`): summary + details → broker `/feedback` → GitHub issue.
struct FeedbackSheet: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(\.appServices) private var services
    let onToast: (String) -> Void

    @State private var summary = ""
    @State private var details = ""
    @State private var busy = false

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("Summary", text: $summary)
                    TextField("Details (optional)", text: $details, axis: .vertical)
                        .lineLimit(3...6)
                }
            }
            .navigationTitle("Send feedback")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Send") { Task { await send() } }
                        .disabled(busy || summary.trimmingCharacters(in: .whitespaces).isEmpty)
                }
            }
        }
        .presentationDetents([.medium, .large])
    }

    private func send() async {
        guard let broker = services?.broker else { return }
        busy = true
        do {
            let res = try await broker.feedback(title: summary.trimmed, body: details.trimmed)
            let number = (res["number"] as? NSNumber)?.intValue
            let copilot = (res["copilot"] as? Bool) == true
            dismiss()
            onToast("Thanks! Filed issue #\(number.map(String.init) ?? "?")"
                    + (copilot ? " — assigned to Copilot" : ""))
        } catch { onToast("Couldn't send feedback: \(error.localizedDescription)") }
        busy = false
    }
}
#endif
