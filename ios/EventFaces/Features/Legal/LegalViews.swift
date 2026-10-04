import SwiftUI

/// "I accept the Terms of Use and am at least 16", with the documents one tap away.
/// Unticked by default; required before signing in (the server records the acceptance).
struct TermsCheckbox: View {
    @Binding var isOn: Bool
    /// Opens a document (pushed inside the sign-in sheet, not a sheet on a sheet).
    let show: (LegalDocumentKind) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Toggle(isOn: $isOn) {
                Text("I accept the Terms of Use and confirm that I am at least 16 years old.")
                    .foregroundStyle(Palette.text)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .toggleStyle(CheckboxStyle())
            .accessibilityIdentifier("accept-terms")
            HStack(spacing: 16) {
                Button("Terms of Use") { show(.terms) }.accessibilityIdentifier("show-terms")
                Button("Privacy Notice") { show(.privacy) }.accessibilityIdentifier("show-privacy")
            }
            .font(.subheadline)
            .foregroundStyle(Palette.accent)
            .buttonStyle(.tapTarget)
        }
    }
}

/// A legal document as the API serves it (the web shows the same version).
struct LegalDocumentView: View {
    let kind: LegalDocumentKind
    /// Pushed inside a sheet's navigation stack (Settings, sign-in) rather than presented.
    var pushed = false
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(spacing: 0) {
            SheetHeader(title: Self.title(kind), closeLabel: pushed ? "Back" : "Close") { dismiss() }
            ScrollView {
                LegalDocumentContent(kind: kind).padding(20).readableWidth()
            }
            .accessibilityIdentifier("legal-document")  // on the scroll view, not the container (IOS-018)
        }
        .background(Palette.bg.ignoresSafeArea())
        .toolbar(.hidden, for: .navigationBar)
        .navigationBarBackButtonHidden(true)
    }

    static func title(_ kind: LegalDocumentKind) -> LocalizedStringKey {
        switch kind {
        case .terms: "Terms of Use"
        case .organizerTerms: "Organizer Terms"
        case .privacy: "Privacy Notice"
        case .imprint: "Legal notice"
        }
    }
}

/// Loads and shows a document; reports the loaded version to `onLoad` (for acceptance).
struct LegalDocumentContent: View {
    let kind: LegalDocumentKind
    var reload = 0  // bump to load again (e.g. the version changed while it was open)
    var onLoad: (LegalDocument) -> Void = { _ in }
    @Environment(AppModel.self) private var model
    @State private var document: LegalDocument?
    @State private var language: String?
    @State private var failed = false

    private var loadKey: [String] { [language ?? "", String(reload)] }

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            if let document {
                text(document)
            } else if failed {
                Banner(kind: .error, text: Text("This document couldn't be loaded. Check your connection and try again."))
            } else {
                ProgressView().frame(maxWidth: .infinity)
            }
        }
        .task(id: loadKey) { await load() }
    }

    @ViewBuilder
    private func text(_ document: LegalDocument) -> some View {
        let german = document.locale.rawValue == "de"
        VStack(alignment: .leading, spacing: 6) {
            Text(verbatim: document.title).font(.title.bold()).foregroundStyle(Palette.text).accessibilityAddTraits(.isHeader)
            // In the document's own language (not the app's): verbatim.
            Group {
                if german { Text(verbatim: "Stand: \(document.version)") } else { Text(verbatim: "Version: \(document.version)") }
            }
            .font(.footnote).foregroundStyle(Palette.textMuted)
            if !german {
                Text(verbatim: "The German version is binding.").font(.footnote).foregroundStyle(Palette.textMuted)
            }
            Button { language = german ? "en" : "de" } label: {
                if german { Text(verbatim: "English translation") } else { Text(verbatim: "Deutsche Fassung (verbindlich)") }
            }
                .font(.subheadline)
                .foregroundStyle(Palette.accent)
                .buttonStyle(.tapTarget)
                .accessibilityIdentifier("legal-language")
        }
        Text(verbatim: document.intro).foregroundStyle(Palette.textMuted).fixedSize(horizontal: false, vertical: true)
        VStack(alignment: .leading, spacing: 18) {
            ForEach(document.sections, id: \.heading) { section in
                VStack(alignment: .leading, spacing: 6) {
                    Text(verbatim: section.heading).font(.headline).foregroundStyle(Palette.text).accessibilityAddTraits(.isHeader)
                    ForEach(Array(section.paragraphs.enumerated()), id: \.offset) { _, paragraph in
                        Text(verbatim: paragraph).foregroundStyle(Palette.textMuted).fixedSize(horizontal: false, vertical: true)
                    }
                }
            }
            // The version again at the end of the document (and the end marker for UI tests).
            Group {
                if german { Text(verbatim: "Stand: \(document.version)") } else { Text(verbatim: "Version: \(document.version)") }
            }
            .font(.footnote).foregroundStyle(Palette.textMuted)
            .accessibilityIdentifier("legal-end")
        }
    }

    private func load() async {
        failed = false
        do {
            let loaded = try await model.auth.legalDocument(kind, language: language)
            document = loaded
            onLoad(loaded)
        } catch {
            failed = document == nil
        }
    }
}

/// Shown when the current Terms (or, for managing events, the Organizer Terms with the
/// data processing agreement) haven't been accepted yet. "Not now" keeps the account,
/// its settings and its deletion available.
struct AcceptLegalView: View {
    let kind: LegalDocumentKind
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var version: String?
    @State private var reload = 0
    @State private var agreed = false
    @State private var busy = false
    @State private var failure: LocalizedStringKey?

    var body: some View {
        VStack(spacing: 0) {
            SheetHeader(title: kind == .organizerTerms ? "Organizer Terms" : "Updated terms", closeLabel: "Not now") { dismiss() }
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    Text(kind == .organizerTerms
                         ? "To manage events, please read and accept the Organizer Terms, including the data processing agreement."
                         : "Please read and accept the current Terms of Use to continue. You can still manage or delete your account without accepting.")
                        .foregroundStyle(Palette.text)
                        .fixedSize(horizontal: false, vertical: true)
                    LegalDocumentContent(kind: kind, reload: reload) { version = $0.version }
                    if let failure { Banner(kind: .error, text: Text(failure)) }
                    Toggle(isOn: $agreed) {
                        Text(kind == .organizerTerms
                             ? "I accept the Organizer Terms and the data processing agreement on behalf of the organizer."
                             : "I accept the Terms of Use and confirm that I am at least 16 years old.")
                            .foregroundStyle(Palette.text)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    .toggleStyle(CheckboxStyle())
                    .accessibilityIdentifier("accept-legal-checkbox")
                    Button {
                        Task { await accept() }
                    } label: {
                        if busy { ProgressView().tint(Palette.onAccent) } else { Text("Accept and continue") }
                    }
                    .buttonStyle(.primary)
                    .disabled(!agreed || busy || version == nil)
                    .accessibilityIdentifier("accept-legal")
                }
                .padding(20)
                .readableWidth()
            }
        }
        .background(Palette.bg.ignoresSafeArea())
        .onDisappear { if model.requiredAcceptance == kind { model.requiredAcceptance = nil } }
    }

    private func accept() async {
        guard let version else { return }
        busy = true
        failure = nil
        defer { busy = false }
        do {
            model.didAccept(try await model.auth.acceptLegal(kind, version: version))
            dismiss()
        } catch AppError.legalChanged {
            failure = "These terms have just changed. Please read the current version."
            self.version = nil
            agreed = false
            reload += 1
        } catch {
            failure = "Couldn't save your acceptance. Try again in a moment."
        }
    }
}
