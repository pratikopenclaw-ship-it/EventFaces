import SwiftUI
import VisionKit

/// Join an event: scan the organizer's QR code or type the access code.
struct JoinView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var code = ""
    @State private var busy = false
    @State private var error: LocalizedStringKey?
    @State private var scanning = false

    var body: some View {
        VStack(spacing: 0) {
            SheetHeader(title: "Join an event") { dismiss() }
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    if let error { Banner(kind: .error, text: Text(error)).accessibilityIdentifier("join-error") }
                    Button {
                        scanning = true
                    } label: {
                        Label("Scan QR code", systemImage: "qrcode.viewfinder")
                    }
                    .buttonStyle(.primary)
                    .accessibilityIdentifier("scan-qr")
                    Text("Or type the access code")
                        .font(.headline)
                        .foregroundStyle(Palette.text)
                        .padding(.top, 8)
                    // Explicit label and a token-coloured prompt: the system placeholder is
                    // too faint and the field otherwise has no accessibility label.
                    TextField("Access code", text: $code, prompt: Text("Access code").foregroundStyle(Palette.textMuted))
                        .accessibilityLabel(Text("Access code"))
                        .textInputAutocapitalization(.characters)
                        .autocorrectionDisabled()
                        .font(.title3)  // no monospaced design: the audit found it stops the field scaling
                        .padding(14)
                        .frame(minHeight: 50)
                        .background(Palette.surface, in: .rect(cornerRadius: 12))
                        .overlay(RoundedRectangle(cornerRadius: 12).stroke(Palette.border))
                        .onChange(of: code) { _, new in code = String(new.uppercased().filter { $0.isLetter || $0.isNumber }.prefix(32)) }
                        .submitLabel(.join)
                        .onSubmit { Task { await join() } }
                        .accessibilityIdentifier("access-code-field")
                    Button {
                        Task { await join() }
                    } label: {
                        if busy { ProgressView().tint(Palette.onAccent) } else { Text("Join event") }
                    }
                    .buttonStyle(.primary)
                    .disabled(code.count < 4 || busy)
                    .accessibilityIdentifier("join-with-code")
                }
                .padding(20)
                .readableWidth()
            }
            .scrollDismissesKeyboard(.immediately)
        }
        .background(Palette.bg.ignoresSafeArea())
        .sheet(isPresented: $scanning) {
            QRScannerView { url in
                scanning = false
                Task { await model.open(url) ; dismiss() }
            } onInvalid: {
                scanning = false
                error = "That QR code isn't an EventFaces event link."
            }
        }
    }

    private func join() async {
        guard code.count >= 4, !busy else { return }
        busy = true
        error = nil
        defer { busy = false }
        do {
            try await model.joinWithCode(code)
            dismiss()
        } catch {
            self.error = JoinMessages.message(for: error)
        }
    }
}

enum JoinMessages {
    static func message(for error: Error) -> LocalizedStringKey {
        switch error {
        case JoinError.invalidCode: "That code didn't work. Check it and try again."
        case JoinError.locked: "Too many wrong codes. Wait 15 minutes, then try again."
        case JoinError.inviteOnly: "This event is invite-only. Use the link from your invitation email."
        case JoinError.ended, AppError.noAccess: "You can't join this event: its access has ended or was revoked."
        case JoinError.inviteForAnotherEmail: "This invitation is for a different email address. Sign in with the address it was sent to."
        case JoinError.inviteExpired: "This invitation has expired or was already used. Ask the organizer for a new one."
        case AppError.offline, is URLError: "You're offline. Check your connection and try again."
        default: "Something went wrong on our side. Try again in a moment."
        }
    }
}

/// Our own sheet header: system toolbar buttons sit on glass and failed the contrast audit.
struct SheetHeader: View {
    let title: LocalizedStringKey
    var closeLabel: LocalizedStringKey = "Cancel"
    let onClose: () -> Void

    var body: some View {
        HStack {
            Button(closeLabel, action: onClose)
                .foregroundStyle(Palette.text)
                .buttonStyle(.tapTarget)
                .accessibilityIdentifier("sheet-close")
            Spacer()
            Text(title).font(.headline).foregroundStyle(Palette.text).accessibilityAddTraits(.isHeader)
            Spacer()
            Color.clear.frame(width: 60, height: 44).accessibilityHidden(true)
        }
        .padding(.horizontal, 16)
        .padding(.top, 8)
        .background(Palette.bg)
    }
}

/// VisionKit's live QR scanner (on-device). Only EventFaces links for the configured host
/// are accepted; anything else is reported, never opened.
struct QRScannerView: View {
    let onLink: (URL) -> Void
    let onInvalid: () -> Void
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @Environment(\.openURL) private var openURL
    @State private var denied = false

    var body: some View {
        VStack(spacing: 0) {
            SheetHeader(title: "Scan QR code") { dismiss() }
            Group {
                if denied {
                    CameraDeniedView(message: "EventFaces needs the camera to scan the event's QR code. Turn it on in Settings.")
                } else if DataScannerViewController.isSupported && DataScannerViewController.isAvailable {
                    DataScannerRepresentable { payload in handle(payload) }
                        .accessibilityLabel("Camera viewfinder for the QR code")
                } else {
                    VStack(spacing: 12) {
                        Image(systemName: "qrcode.viewfinder").font(.system(size: 48)).foregroundStyle(Palette.textMuted).accessibilityHidden(true)
                        Text("QR scanning isn't available on this device. Type the access code instead.")
                            .multilineTextAlignment(.center)
                            .foregroundStyle(Palette.textMuted)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    .padding(32)
                    .frame(maxHeight: .infinity)
                }
            }
        }
        .background(Palette.bg.ignoresSafeArea())
        .task {
            #if DEBUG
            // UI tests: a scanned payload without a camera (the simulator has none).
            if let i = ProcessInfo.processInfo.arguments.firstIndex(of: "-ui-testing-scan"),
               ProcessInfo.processInfo.arguments.indices.contains(i + 1) {
                handle(ProcessInfo.processInfo.arguments[i + 1])
                return
            }
            #endif
            do { try await CameraFrameSource.authorize() } catch { denied = true }
        }
    }

    private func handle(_ payload: String) {
        if let url = URL(string: payload), DeepLink.parse(url, allowedHost: model.config.appLinkHost) != nil {
            onLink(url)
        } else {
            onInvalid()
        }
    }
}

private struct DataScannerRepresentable: UIViewControllerRepresentable {
    let onPayload: (String) -> Void

    func makeUIViewController(context: Context) -> DataScannerViewController {
        let vc = DataScannerViewController(recognizedDataTypes: [.barcode(symbologies: [.qr])], qualityLevel: .balanced,
                                           isHighFrameRateTrackingEnabled: false, isHighlightingEnabled: true)
        vc.delegate = context.coordinator
        try? vc.startScanning()
        return vc
    }

    func updateUIViewController(_ vc: DataScannerViewController, context: Context) {}
    func makeCoordinator() -> Coordinator { Coordinator(onPayload: onPayload) }

    final class Coordinator: NSObject, DataScannerViewControllerDelegate {
        let onPayload: (String) -> Void
        private var done = false
        init(onPayload: @escaping (String) -> Void) { self.onPayload = onPayload }

        func dataScanner(_ scanner: DataScannerViewController, didAdd items: [RecognizedItem], allItems: [RecognizedItem]) {
            guard !done else { return }
            for case let .barcode(code) in items {
                if let payload = code.payloadStringValue {
                    done = true
                    scanner.stopScanning()
                    onPayload(payload)
                    return
                }
            }
        }
    }
}

/// Camera permission was denied: explain and offer Settings (never a dead end).
struct CameraDeniedView: View {
    let message: LocalizedStringKey
    @Environment(\.openURL) private var openURL

    var body: some View {
        VStack(spacing: 16) {
            Image(systemName: "camera.fill").font(.system(size: 44)).foregroundStyle(Palette.textMuted).accessibilityHidden(true)
            Text("Camera access is off").font(.title3.bold()).foregroundStyle(Palette.text).accessibilityAddTraits(.isHeader)
            Text(message)
                .multilineTextAlignment(.center)
                .foregroundStyle(Palette.textMuted)
                .fixedSize(horizontal: false, vertical: true)
            Button("Open Settings") {
                if let url = URL(string: UIApplication.openSettingsURLString) { openURL(url) }
            }
            .buttonStyle(.primary)
            .accessibilityIdentifier("open-camera-settings")
        }
        .padding(32)
        .readableWidth()
        .frame(maxHeight: .infinity)
        .accessibilityIdentifier("camera-denied")
    }
}
