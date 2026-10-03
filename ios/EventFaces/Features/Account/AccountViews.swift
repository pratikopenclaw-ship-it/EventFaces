import SwiftUI

/// Settings › Privacy: consent status, "Delete my data", app lock.
struct PrivacySection: View {
    @Environment(AppModel.self) private var model
    @State private var consent: ConsentInfo?
    @State private var confirmWithdraw = false
    @State private var message: LocalizedStringKey?

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            if let message { Banner(kind: .info, text: Text(message)).padding(.vertical, 8) }
            ValueRowView(title: "Face-search consent", value: consentText)
            Divider().overlay(Palette.border)
            RowAction(title: "Delete my data", color: Palette.dangerText) { confirmWithdraw = true }
                .accessibilityIdentifier("delete-my-data")
            Divider().overlay(Palette.border)
            Toggle(isOn: Binding(get: { model.lock.enabled }, set: { on in Task { await model.lock.setEnabled(on, reason: String(localized: "Turn on the app lock")) } })) {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Lock with \(model.lock.biometryName)").foregroundStyle(Palette.text)
                    Text("Asks when you come back to the app.").font(.footnote).foregroundStyle(Palette.textMuted)
                }
            }
            .tint(Palette.accent)
            .disabled(!model.lock.isAvailable)
            .frame(minHeight: 56)
            .accessibilityIdentifier("app-lock")
        }
        .task { consent = try? await model.events.consent() }
        .alert("Delete your face-search data?", isPresented: $confirmWithdraw) {
            Button("Delete my data", role: .destructive) { Task { await withdraw() } }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("We'll withdraw your consent and delete the list of photos we matched for you. Your account stays. You'll be asked again before your next search.")
        }
    }

    private var consentText: String {
        guard let consent else { return "…" }
        return consent.given ? String(localized: "Given") : String(localized: "Not given")
    }

    private func withdraw() async {
        do {
            try await model.auth.withdrawConsent()
            await PhotoCache.shared.purgeAll()
            consent = try? await model.events.consent()
            message = "Done. Your matches were deleted and you'll be asked again before your next search."
        } catch {
            message = "Something went wrong on our side. Try again in a moment."
        }
    }
}

/// Settings › Devices: where you're signed in; sign out the others remotely.
struct DevicesSection: View {
    @Environment(AppModel.self) private var model
    @State private var devices: [DeviceInfo] = []

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            ForEach(devices, id: \.id) { device in
                HStack {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(device.name).foregroundStyle(Palette.text)
                        let lastUsed = device.lastSeenAt.formatted(date: .abbreviated, time: .omitted)
                        Text(device.current == true ? String(localized: "This device") : String(localized: "Last used \(lastUsed)"))
                            .font(.footnote).foregroundStyle(Palette.textMuted)
                    }
                    Spacer()
                    if device.current != true {
                        Button("Sign out") { Task { try? await model.auth.revokeDevice(device.id); await load() } }
                            .foregroundStyle(Palette.dangerText)
                            .buttonStyle(.tapTarget)
                    }
                }
                .frame(minHeight: 56)
                .accessibilityElement(children: .combine)
                if device.id != devices.last?.id { Divider().overlay(Palette.border) }
            }
        }
        .task { await load() }
    }

    private func load() async { devices = (try? await model.auth.devices()) ?? devices }
}

/// "Delete my account": confirmed with a code we email (accounts made in the app have no password).
struct DeleteAccountView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var code = ""
    @State private var sent = false
    @State private var busy = false
    @State private var error: LocalizedStringKey?

    var body: some View {
        VStack(spacing: 0) {
            SheetHeader(title: "Delete account") { dismiss() }
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    Text("This permanently deletes your account, your event memberships, the photos you matched, the photos you uploaded and your devices. It can't be undone.")
                        .foregroundStyle(Palette.text).fixedSize(horizontal: false, vertical: true)
                    if let error { Banner(kind: .error, text: Text(error)) }
                    if !sent {
                        Button("Email me a confirmation code") { Task { await send() } }
                            .buttonStyle(.secondary)
                            .disabled(busy)
                            .accessibilityIdentifier("send-deletion-code")
                    } else {
                        TextField("6-digit code", text: $code)
                            .keyboardType(.numberPad)
                            .textContentType(.oneTimeCode)
                            .font(.title2).monospacedDigit()
                            .padding(14)
                            .background(Palette.surface, in: .rect(cornerRadius: 12))
                            .overlay(RoundedRectangle(cornerRadius: 12).stroke(Palette.border))
                            .onChange(of: code) { _, v in code = String(v.filter(\.isNumber).prefix(6)) }
                            .accessibilityIdentifier("deletion-code")
                        Button("Delete my account") { Task { await delete() } }
                            .buttonStyle(DangerButtonStyle())
                            .disabled(code.count != 6 || busy)
                            .accessibilityIdentifier("confirm-delete-account")
                    }
                }
                .padding(20)
                .readableWidth()
            }
        }
        .background(Palette.bg.ignoresSafeArea())
    }

    private func send() async {
        busy = true
        defer { busy = false }
        do { try await model.auth.sendDeletionCode(); sent = true; error = nil } catch { self.error = "Something went wrong on our side. Try again in a moment." }
    }

    private func delete() async {
        busy = true
        defer { busy = false }
        do {
            try await model.auth.deleteAccount(code: code)
            await model.didDeleteAccount()
            dismiss()
        } catch AppError.invalidCode {
            error = "That code didn't work. Check it or send a new one."
            code = ""
        } catch {
            self.error = "Something went wrong on our side. Try again in a moment."
        }
    }
}

struct DangerButtonStyle: ButtonStyle {
    @Environment(\.isEnabled) private var isEnabled
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.body.weight(.semibold))
            .frame(maxWidth: .infinity, minHeight: 50)
            .foregroundStyle(isEnabled ? Palette.surface : Palette.textMuted)
            .background(isEnabled ? Palette.danger : Palette.surface2, in: .rect(cornerRadius: 12))
            .opacity(configuration.isPressed ? 0.85 : 1)
    }
}

/// Shared rows (Settings uses private copies; these are for the account sections).
struct ValueRowView: View {
    let title: LocalizedStringKey
    let value: String
    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(title).font(.subheadline).foregroundStyle(Palette.textMuted)
            Text(value).font(.body).foregroundStyle(Palette.text)
        }
        .frame(maxWidth: .infinity, minHeight: 50, alignment: .leading)
        .padding(.vertical, 6)
        .accessibilityElement(children: .combine)
    }
}

struct RowAction: View {
    let title: LocalizedStringKey
    let color: Color
    let action: () -> Void
    var body: some View {
        Button(action: action) {
            Text(title).font(.body).foregroundStyle(color)
                .frame(maxWidth: .infinity, minHeight: 50, alignment: .leading)
                .contentShape(.rect)
        }
        .buttonStyle(.plain)
    }
}

/// Shown over everything while the app lock is engaged.
struct LockScreen: View {
    @Environment(AppModel.self) private var model
    var body: some View {
        VStack(spacing: 18) {
            Image(systemName: "lock.fill").font(.system(size: 44)).foregroundStyle(Palette.accent).accessibilityHidden(true)
            Text("EventFaces is locked").font(.title2.bold()).foregroundStyle(Palette.text)
            Button("Unlock with \(model.lock.biometryName)") { Task { await model.lock.unlock(reason: String(localized: "Unlock EventFaces")) } }
                .buttonStyle(.primary)
                .accessibilityIdentifier("unlock")
        }
        .padding(32)
        .readableWidth()
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Palette.bg.ignoresSafeArea())
        .task { await model.lock.unlock(reason: String(localized: "Unlock EventFaces")) }
    }
}
