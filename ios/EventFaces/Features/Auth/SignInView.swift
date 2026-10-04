import OpenAPIRuntime
import SwiftUI

extension ClientError: ClientErrorWithUnderlying {
    var underlying: any Error { underlyingError }
}

/// Passwordless sign-in: email, then the 6-digit code from the email (or tap the link in it).
struct SignInView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var vm: SignInViewModel?
    @State private var shownDocument: LegalDocumentKind?
    @FocusState private var focused: Bool

    var body: some View {
        NavigationStack {
            // Scrolls at large Dynamic Type sizes instead of clipping.
            ScrollView {
                Group {
                    if let vm { content(vm) }
                }
                .padding(24)
                .readableWidth()
            }
            .scrollDismissesKeyboard(.immediately)  // the number pad has no key to close it
            .navigationDestination(item: $shownDocument) { LegalDocumentView(kind: $0, pushed: true) }
            .background(Palette.bg.ignoresSafeArea())
            .navigationTitle("Sign in")
            .navigationBarTitleDisplayMode(.inline)
            .toolbarBackground(Palette.bg, for: .navigationBar)
            .safeAreaInset(edge: .top) {
                // Our own header instead of a toolbar item: iOS 27 draws toolbar buttons on
                // translucent glass, where the text failed the contrast audit.
                HStack {
                    Button("Cancel") { dismiss() }
                        .foregroundStyle(Palette.text)
                        .buttonStyle(.tapTarget)
                        .accessibilityIdentifier("sign-in-cancel")
                    Spacer()
                }
                .padding(.horizontal, 16)
                .background(Palette.bg)
            }
        }
        .onAppear { if vm == nil { vm = SignInViewModel(auth: model.auth) } }
        .onDisappear { model.cancelMagicSignIn() }
    }

    @ViewBuilder
    private func content(_ vm: SignInViewModel) -> some View {
        @Bindable var vm = vm
        VStack(alignment: .leading, spacing: 16) {
            if let error = vm.error {
                Banner(kind: .error, text: Text(message(for: error)))
                    .accessibilityIdentifier("sign-in-error")
            }
            if model.pendingMagicToken != nil {
                magicLinkConfirmation(vm)
            } else {
                steps(vm)
            }
        }
    }

    /// A sign-in link opened without ticking the Terms in this app first: ask now.
    @ViewBuilder
    private func magicLinkConfirmation(_ vm: SignInViewModel) -> some View {
        @Bindable var vm = vm
        Text("Almost there. Please accept the Terms of Use to finish signing in.")
            .foregroundStyle(Palette.text)
            .fixedSize(horizontal: false, vertical: true)
        TermsCheckbox(isOn: $vm.acceptedTerms) { shownDocument = $0 }
        Button("Sign in") { Task { await model.completeMagicSignIn() } }
            .buttonStyle(.primary)
            .disabled(!vm.acceptedTerms)
            .accessibilityIdentifier("confirm-magic-sign-in")
    }

    @ViewBuilder
    private func steps(_ vm: SignInViewModel) -> some View {
        @Bindable var vm = vm
        VStack(alignment: .leading, spacing: 16) {
            switch vm.step {
            case .email:
                Text("We'll email you a 6-digit code. No password needed.")
                    .foregroundStyle(Palette.textMuted)
                    .fixedSize(horizontal: false, vertical: true)
                TextField("Email address", text: $vm.email, prompt: Text("Email address").foregroundStyle(Palette.textMuted))
                    .accessibilityLabel(Text("Email address"))
                    .textContentType(.emailAddress)
                    .keyboardType(.emailAddress)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .submitLabel(.send)
                    .focused($focused)
                    .onSubmit {
                        model.termsTickedForSignIn = vm.acceptedTerms
                        Task { await vm.sendCode() }
                    }
                    .padding(14)
                    .frame(minHeight: 50)
                    .background(Palette.surface, in: .rect(cornerRadius: 12))
                    .overlay(RoundedRectangle(cornerRadius: 12).stroke(Palette.border))
                    .accessibilityIdentifier("email-field")
                TermsCheckbox(isOn: $vm.acceptedTerms) { shownDocument = $0 }
                Button {
                    model.termsTickedForSignIn = vm.acceptedTerms
                    Task { await vm.sendCode() }
                } label: {
                    if vm.busy { ProgressView().tint(Palette.onAccent) } else { Text("Send code") }
                }
                .buttonStyle(.primary)
                .disabled(!vm.canSendCode)
                .accessibilityIdentifier("send-code")
            case .code:
                Text("Enter the code we sent to \(vm.email). You can also tap the link in that email.")
                    .foregroundStyle(Palette.textMuted)
                    .fixedSize(horizontal: false, vertical: true)
                TextField("6-digit code", text: $vm.code, prompt: Text("6-digit code").foregroundStyle(Palette.textMuted))
                    .accessibilityLabel(Text("6-digit code"))
                    .textContentType(.oneTimeCode)
                    .keyboardType(.numberPad)
                    .font(.title2).monospacedDigit()  // view modifier: the Font variant stops the field scaling
                    .focused($focused)
                    .padding(14)
                    .frame(minHeight: 50)
                    .background(Palette.surface, in: .rect(cornerRadius: 12))
                    .overlay(RoundedRectangle(cornerRadius: 12).stroke(Palette.border))
                    .accessibilityIdentifier("code-field")
                    .onChange(of: vm.code) { _, new in
                        if new.count == 6 { Task { await submit(vm) } }
                    }
                Button {
                    Task { await submit(vm) }
                } label: {
                    if vm.busy { ProgressView().tint(Palette.onAccent) } else { Text("Sign in") }
                }
                .buttonStyle(.primary)
                .disabled(vm.code.count != 6 || vm.busy)
                .accessibilityIdentifier("verify-code")
                HStack {
                    Button("Use another email") { vm.changeEmail() }
                    Spacer()
                    Button("Send a new code") { Task { await vm.sendCode() } }
                        .disabled(!vm.canResend || vm.busy)
                }
                .font(.subheadline)
                .foregroundStyle(Palette.accent)
                .buttonStyle(.tapTarget)
            }
        }
        // Each step's field takes the keyboard once it is on screen.
        .task(id: vm.step) {
            try? await Task.sleep(for: .milliseconds(350))
            focused = true
        }
    }

    private func submit(_ vm: SignInViewModel) async {
        if let user = await vm.verify() {
            UINotificationFeedbackGenerator().notificationOccurred(.success)
            model.didSignIn(user)
            dismiss()
        } else {
            UINotificationFeedbackGenerator().notificationOccurred(.error)
        }
    }

    private func message(for error: AppError) -> LocalizedStringKey {
        switch error {
        case .invalidCode: "That code didn't work. Check it or send a new one."
        case .linkExpired: "This sign-in link has expired or was already used. Request a new code."
        case .tooManyAttempts: "Too many tries. Wait a few minutes, then try again."
        case .offline: "You're offline. Check your connection and try again."
        case .sessionEnded: "You were signed out. Sign in again to continue."
        case .noAccess, .consentRequired, .legalChanged, .server: "Something went wrong on our side. Try again in a moment."
        }
    }
}
