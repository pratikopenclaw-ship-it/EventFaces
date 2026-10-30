import SwiftUI

/// Settings in a sheet with our own header (a system nav bar's glass buttons failed the
/// contrast audit).
struct SettingsSheet: View {
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        // A navigation stack (bar hidden, our own header) so documents open inside this
        // sheet: a sheet stacked on a sheet is shrunk on iPad and its geometry no longer
        // matches what's on screen.
        NavigationStack {
            content.toolbar(.hidden, for: .navigationBar)
        }
    }

    private var content: some View {
        VStack(spacing: 0) {
            HStack {
                Text("Settings")
                    .font(.headline)
                    .foregroundStyle(Palette.text)
                    .accessibilityAddTraits(.isHeader)
                Spacer()
                Button("Done") { dismiss() }
                    .font(.body.weight(.semibold))
                    .foregroundStyle(Palette.text)
                    .buttonStyle(.tapTarget)
                    .accessibilityIdentifier("settings-done")
            }
            .padding(.horizontal, 20)
            .padding(.top, 8)
            .background(Palette.bg)
            SettingsView()
        }
        .background(Palette.bg.ignoresSafeArea())
    }
}

/// Settings built from our own components (not `Form`): every colour is a token and every
/// text scales with Dynamic Type. The system form's internals failed the accessibility
/// audit (contrast through its materials, fixed-size labels, clipped rows).
struct SettingsView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.openURL) private var openURL
    @State private var showDelete = false
    @State private var shownDocument: LegalDocumentKind?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                section("Appearance", footer: "Photos always display on a dark background.") {
                    ForEach(ThemePreference.allCases, id: \.self) { theme in
                        ThemeRow(theme: theme, selected: model.theme == theme) { model.setTheme(theme) }
                        if theme != ThemePreference.allCases.last { Divider().overlay(Palette.border) }
                    }
                }
                section("Language") {
                    RowAction(title: "Change app language", color: Palette.accent) {
                        if let url = URL(string: UIApplication.openSettingsURLString) { openURL(url) }
                    }
                }
                section("Account") {
                    switch model.account {
                    case let .signedIn(user):
                        ValueRow(title: "Email", value: user.email)
                        Divider().overlay(Palette.border)
                        RowAction(title: "Sign out", color: Palette.dangerText) { Task { await model.signOut() } }
                            .accessibilityIdentifier("sign-out")
                    default:
                        RowAction(title: "Sign in", color: Palette.accent) { model.showSignIn = true }
                    }
                }
                if case let .signedIn(user) = model.account {
                    section("New-photo alerts", footer: "You can also turn them off for a single event on its screen.") {
                        NewPhotoAlertsRow(on: user.newPhotoAlerts ?? true)
                    }
                    section("Privacy") { PrivacySection() }
                    section("Devices", footer: "Sign out a phone or tablet you no longer use.") { DevicesSection() }
                    section("Delete account") {
                        RowAction(title: "Delete my account", color: Palette.dangerText) { showDelete = true }
                            .accessibilityIdentifier("delete-account")
                    }
                }
                section("About") {
                    RowAction(title: "Privacy Notice", color: Palette.accent) { shownDocument = .privacy }
                        .accessibilityIdentifier("about-privacy")
                    Divider().overlay(Palette.border)
                    RowAction(title: "Terms of Use", color: Palette.accent) { shownDocument = .terms }
                        .accessibilityIdentifier("about-terms")
                    Divider().overlay(Palette.border)
                    RowAction(title: "Organizer Terms", color: Palette.accent) { shownDocument = .organizerTerms }
                        .accessibilityIdentifier("about-organizer-terms")
                    Divider().overlay(Palette.border)
                    RowAction(title: "Legal notice", color: Palette.accent) { shownDocument = .imprint }
                        .accessibilityIdentifier("about-imprint")
                    Divider().overlay(Palette.border)
                    RowAction(title: "Contact us", color: Palette.accent) { openURL(model.config.contactURL) }
                        .accessibilityIdentifier("about-contact")
                        .accessibilityHint(Text("Opens the contact form on the website"))
                    Divider().overlay(Palette.border)
                    ValueRow(title: "Version", value: model.config.appVersion)
                }
            }
            .padding(20)
            .readableWidth()
        }
        .background(Palette.bg.ignoresSafeArea())
        .sheet(isPresented: $showDelete) { DeleteAccountView().sheetContent() }
        .navigationDestination(item: $shownDocument) { LegalDocumentView(kind: $0, pushed: true) }
    }

    private func section<Content: View>(_ title: LocalizedStringKey, footer: LocalizedStringKey? = nil, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title)
                .font(.headline)
                .foregroundStyle(Palette.text)
                .accessibilityAddTraits(.isHeader)
            VStack(alignment: .leading, spacing: 0) { content() }
                .padding(.horizontal, 16)
                // Rows clear of the border line: a single-row card otherwise puts the 1 pt
                // stroke on its row's edges, and the contrast audit reads the stroke as text.
                .padding(.vertical, 2)
                .background(Palette.surface, in: .rect(cornerRadius: 14))
                .overlay(RoundedRectangle(cornerRadius: 14).stroke(Palette.border))
            if let footer {
                Text(footer)
                    .font(.footnote)
                    .foregroundStyle(Palette.textMuted)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }
}

/// The account-wide switch (PATCH /api/me/preferences); the profile is the source of truth.
private struct NewPhotoAlertsRow: View {
    let on: Bool
    @Environment(AppModel.self) private var model
    @State private var failed = false

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Toggle(isOn: Binding(get: { on }, set: { v in Task { await save(v) } })) {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Tell me about new photos").foregroundStyle(Palette.text)
                    Text("At events you searched, at most once a day per event.").font(.footnote).foregroundStyle(Palette.textMuted)
                }
            }
            .tint(Palette.accent)
            .frame(minHeight: 56)
            .accessibilityIdentifier("new-photo-alerts")
            if failed {
                Text("Couldn't save. Check your connection and try again.")
                    .font(.footnote)
                    .foregroundStyle(Palette.dangerText)
                    .padding(.bottom, 8)
            }
        }
    }

    private func save(_ v: Bool) async {
        do {
            try await model.setNewPhotoAlerts(v)
            failed = false
        } catch {
            failed = true
        }
    }
}

/// One theme option: a full-width, 44 pt+ row that reports its selected state.
private struct ThemeRow: View {
    let theme: ThemePreference
    let selected: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 12) {
                Image(systemName: theme.symbol).accessibilityHidden(true)
                Text(theme.label).frame(maxWidth: .infinity, alignment: .leading)
                if selected {
                    Image(systemName: "checkmark").fontWeight(.semibold).foregroundStyle(Palette.accent).accessibilityHidden(true)
                }
            }
            .font(.body)
            .foregroundStyle(Palette.text)
            .frame(minHeight: 50)
            .contentShape(.rect)
        }
        .buttonStyle(.plain)
        .accessibilityAddTraits(selected ? [.isSelected] : [])
        .accessibilityIdentifier("theme-\(theme.rawValue)")
    }
}

/// Label above value: scales with Dynamic Type; long emails wrap instead of truncating.
private struct ValueRow: View {
    let title: LocalizedStringKey
    let value: String

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(title).font(.subheadline).foregroundStyle(Palette.textMuted)
            Text(value).font(.body).foregroundStyle(Palette.text).textSelection(.enabled)
        }
        .frame(maxWidth: .infinity, minHeight: 50, alignment: .leading)
        .padding(.vertical, 6)
        .accessibilityElement(children: .combine)
    }
}
