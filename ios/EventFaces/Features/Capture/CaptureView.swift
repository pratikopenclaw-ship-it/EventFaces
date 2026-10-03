import AVFoundation
import SwiftUI

/// Guided selfie capture (camera only: there is no photo-library path for selfies).
struct CaptureView: View {
    let eventID: String
    let onClose: () -> Void
    @Environment(AppModel.self) private var model
    @State private var capture: CaptureModel?

    var body: some View {
        VStack(spacing: 0) {
            SheetHeader(title: "Find my photos", closeLabel: "Close") {
                capture?.stop()
                onClose()
            }
            if let capture { content(capture) } else { Spacer() }
        }
        .background(Palette.bg.ignoresSafeArea())
        .onAppear {
            if capture == nil { capture = CaptureModel(eventID: eventID, service: model.events, source: model.makeFrameSource()) }
        }
        .onDisappear { capture?.stop() }
    }

    @ViewBuilder
    private func content(_ capture: CaptureModel) -> some View {
        switch capture.phase {
        case .intro:
            CaptureIntro { Task { await capture.start() } }
        case .starting:
            ProgressView().frame(maxHeight: .infinity)
        case let .capturing(shot):
            CameraStage(capture: capture, shot: shot)
        case .submitting:
            VStack(spacing: 16) {
                ProgressView()
                Text("Checking your photos…").foregroundStyle(Palette.text)
            }
            .frame(maxHeight: .infinity)
            .accessibilityElement(children: .combine)
        case .paused:
            PausedTips(message: capture.rejection.map { RejectionMessages.text(code: $0.code, serverMessage: $0.message) }) { Task { await capture.retryAfterPause() } }
        case .found:
            ResultsView(eventID: eventID)
        case .queued:
            QueuedView(eventID: eventID)
        case let .failed(failure):
            FailureView(failure: failure) {
                Task { await capture.start() }
            }
        }
    }
}

private struct CaptureIntro: View {
    let onStart: () -> Void

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                Text("Before you take your selfies").font(.title2.bold()).foregroundStyle(Palette.text).accessibilityAddTraits(.isHeader)
                Text("Three quick photos help us find you reliably. They're deleted right after matching.")
                    .foregroundStyle(Palette.textMuted).fixedSize(horizontal: false, vertical: true)
                tip("sun.max", "Good, even light on your face", "Face a window or lamp; avoid bright light behind you.")
                tip("face.smiling", "Face the camera", "We'll ask for one straight photo and two with your head turned slightly.")
                tip("eyeglasses", "No sunglasses, mask or hat", "Normal glasses are fine.")
                tip("person", "Just you", "No other people in the picture.")
                tip("hand.raised", "Hold still", "Photos are taken automatically when everything looks good.")
                Button("Start camera", action: onStart).buttonStyle(.primary).padding(.top, 8).accessibilityIdentifier("start-camera")
            }
            .padding(20)
            .readableWidth()
        }
    }

    private func tip(_ symbol: String, _ title: LocalizedStringKey, _ body: LocalizedStringKey) -> some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: symbol).font(.title3).foregroundStyle(Palette.accent).frame(width: 28).accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(.headline).foregroundStyle(Palette.text)
                Text(body).foregroundStyle(Palette.textMuted).fixedSize(horizontal: false, vertical: true)
            }
        }
        .accessibilityElement(children: .combine)
    }
}

private struct CameraStage: View {
    let capture: CaptureModel
    let shot: CaptureShot

    var body: some View {
        VStack(spacing: 14) {
            if let rejection = capture.rejection {
                Banner(kind: .error, text: RejectionMessages.text(code: rejection.code, serverMessage: rejection.message)).accessibilityIdentifier("rejection")
            }
            ShotProgress(current: shot, done: capture.completed)
            Text(shot.instruction).font(.headline).foregroundStyle(Palette.text).multilineTextAlignment(.center)
            ZStack {
                Color.black
                CameraPreview(source: capture.source)
                FaceOval(ok: capture.guidance == .ok)
                VStack {
                    Spacer()
                    Text(capture.guidance.hint)
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(.white)
                        .padding(.horizontal, 14)
                        .padding(.vertical, 8)
                        .background(.black.opacity(0.75), in: .capsule)
                        .padding(.bottom, 14)
                        .accessibilityIdentifier("guidance")
                        .accessibilityAddTraits(.updatesFrequently)
                }
            }
            .aspectRatio(3 / 4, contentMode: .fit)
            .clipShape(.rect(cornerRadius: 16))
            .accessibilityElement(children: .contain)
            .accessibilityLabel("Camera")
            .accessibilityValue(Text(capture.guidance.hint))
            if capture.manualAvailable {
                Button("Take this photo now") { capture.captureNow() }
                    .buttonStyle(.secondary)
                    .accessibilityIdentifier("capture-now")
            }
            Spacer(minLength: 0)
        }
        .padding(16)
        .readableWidth()
        .accessibilityIdentifier("shot-\(shot.rawValue)")
    }
}

private struct ShotProgress: View {
    let current: CaptureShot
    let done: [CaptureShot]

    var body: some View {
        HStack(spacing: 8) {
            ForEach(CaptureShot.allCases, id: \.self) { shot in
                let isDone = done.contains(shot)
                Image(systemName: isDone ? "checkmark.circle.fill" : (shot == current ? "circle.inset.filled" : "circle"))
                    .foregroundStyle(isDone ? Palette.success : (shot == current ? Palette.accent : Palette.textMuted))
                    .accessibilityHidden(true)
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(Text("Photo \(done.count + 1) of 3"))
    }
}

private struct FaceOval: View {
    let ok: Bool
    var body: some View {
        GeometryReader { geo in
            Ellipse()
                .stroke(ok ? Palette.success : .white.opacity(0.8), style: StrokeStyle(lineWidth: 4, dash: ok ? [] : [10, 8]))
                .frame(width: geo.size.width * 0.58, height: geo.size.height * 0.62)
                .position(x: geo.size.width / 2, y: geo.size.height / 2)
        }
        .accessibilityHidden(true)
    }
}

/// The live preview (mirrored like a mirror; the captured frames are not).
private struct CameraPreview: UIViewRepresentable {
    let source: FrameSource

    func makeUIView(context: Context) -> PreviewView { PreviewView(source: source) }
    func updateUIView(_ view: PreviewView, context: Context) { view.refresh() }

    final class PreviewView: UIView {
        let source: FrameSource
        private let imageView = UIImageView()

        init(source: FrameSource) {
            self.source = source
            super.init(frame: .zero)
            imageView.contentMode = .scaleAspectFill
            imageView.transform = CGAffineTransform(scaleX: -1, y: 1)
            addSubview(imageView)
            clipsToBounds = true
        }

        required init?(coder: NSCoder) { fatalError() }

        override func layoutSubviews() {
            super.layoutSubviews()
            MainActor.assumeIsolated {
                if let layer = source.previewLayer {
                    if layer.superlayer == nil { self.layer.addSublayer(layer) }
                    layer.frame = bounds
                }
                imageView.frame = bounds
            }
        }

        func refresh() {
            #if DEBUG
            if let fake = source as? FakeFrameSource { imageView.image = fake.latest }
            #endif
            setNeedsLayout()
        }
    }
}

private struct PausedTips: View {
    let message: Text?
    let onRetry: () -> Void

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                Text("Let's try that again").font(.title2.bold()).foregroundStyle(Palette.text).accessibilityAddTraits(.isHeader)
                if let message { Banner(kind: .error, text: message) }
                Text("A few things that usually help:").foregroundStyle(Palette.textMuted)
                Label("Move to brighter, even light", systemImage: "sun.max").foregroundStyle(Palette.text)
                Label("Hold the phone at eye level", systemImage: "iphone").foregroundStyle(Palette.text)
                Label("Take off sunglasses, masks or hats", systemImage: "eyeglasses").foregroundStyle(Palette.text)
                Label("Keep still for a moment", systemImage: "hand.raised").foregroundStyle(Palette.text)
                Button("Try again", action: onRetry).buttonStyle(.primary).padding(.top, 8).accessibilityIdentifier("try-again")
            }
            .padding(20)
            .readableWidth()
        }
        .accessibilityIdentifier("paused")
    }
}

private struct FailureView: View {
    let failure: CaptureModel.Failure
    let onRetry: () -> Void

    var body: some View {
        switch failure {
        case .cameraDenied:
            CameraDeniedView(message: "EventFaces needs the camera to take your selfies. Turn it on in Settings.")
        default:
            VStack(spacing: 16) {
                Banner(kind: .error, text: Text(message))
                if failure != .alreadyQueued && failure != .noAccess {
                    Button("Try again", action: onRetry).buttonStyle(.primary)
                }
            }
            .padding(20)
            .readableWidth()
            .frame(maxHeight: .infinity, alignment: .top)
            .accessibilityIdentifier("capture-failed")
        }
    }

    private var message: LocalizedStringKey {
        switch failure {
        case .cameraDenied: "Camera access is off"
        case .cameraUnavailable: "The camera isn't available right now. Close other apps that use it and try again."
        case .consentRequired: "The consent text has changed. Close this screen and review it again."
        case .noAccess: "You don't have access to this event (any more)."
        case .busy: "Lots of people are searching right now. Try again in a few seconds."
        case .alreadyQueued: "Your earlier search is still in the queue. We'll let you know when it's done."
        case .offline: "You're offline. Check your connection and try again."
        case .server: "Something went wrong on our side. Try again in a moment."
        }
    }
}
