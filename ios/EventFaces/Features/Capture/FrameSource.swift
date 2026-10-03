@preconcurrency import AVFoundation
import CoreImage
import UIKit

/// Where camera frames come from. Frames stay in memory: never written, cached or logged.
@MainActor
protocol FrameSource: AnyObject {
    /// Called on the main actor for every frame (the newest wins; analysis drops frames it can't keep up with).
    var onFrame: ((CVPixelBuffer) -> Void)? { get set }
    /// The live preview (camera) or the latest frame (fake source).
    var previewLayer: AVCaptureVideoPreviewLayer? { get }
    func start() async throws
    func stop()
    /// Which shot the user is on: the fake source shows the matching test frame.
    func setShot(_ shot: CaptureShot)
}

enum CaptureShot: String, CaseIterable, Sendable {
    case front, left, right
}

enum CameraError: Error, Equatable {
    case denied
    case unavailable
}

/// The front camera, portrait, unmirrored frames (the server sees what the camera sees;
/// only the on-screen preview is mirrored, like a mirror).
@MainActor
final class CameraFrameSource: NSObject, FrameSource {
    var onFrame: ((CVPixelBuffer) -> Void)?
    private(set) var previewLayer: AVCaptureVideoPreviewLayer?
    // Used from the camera queue only after configuration (Apple's documented pattern).
    nonisolated(unsafe) private let session = AVCaptureSession()
    private let output = AVCaptureVideoDataOutput()
    private let queue = DispatchQueue(label: "app.eventfaces.camera")

    static func authorize() async throws {
        switch AVCaptureDevice.authorizationStatus(for: .video) {
        case .authorized: return
        case .notDetermined:
            guard await AVCaptureDevice.requestAccess(for: .video) else { throw CameraError.denied }
        default: throw CameraError.denied
        }
    }

    func start() async throws {
        try await Self.authorize()
        guard let device = AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: .front),
              let input = try? AVCaptureDeviceInput(device: device), session.canAddInput(input)
        else { throw CameraError.unavailable }
        session.beginConfiguration()
        session.sessionPreset = .hd1280x720
        session.addInput(input)
        output.videoSettings = [kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA]
        output.alwaysDiscardsLateVideoFrames = true
        output.setSampleBufferDelegate(self, queue: queue)
        if session.canAddOutput(output) { session.addOutput(output) }
        if let connection = output.connection(with: .video) {
            if connection.isVideoRotationAngleSupported(90) { connection.videoRotationAngle = 90 }  // portrait
            if connection.isVideoMirroringSupported { connection.automaticallyAdjustsVideoMirroring = false; connection.isVideoMirrored = false }
        }
        session.commitConfiguration()
        let layer = AVCaptureVideoPreviewLayer(session: session)
        layer.videoGravity = .resizeAspectFill
        previewLayer = layer
        queue.async { [session] in session.startRunning() }
    }

    func stop() {
        queue.async { [session] in session.stopRunning() }
    }

    func setShot(_ shot: CaptureShot) {}
}

extension CameraFrameSource: AVCaptureVideoDataOutputSampleBufferDelegate {
    nonisolated func captureOutput(_ output: AVCaptureOutput, didOutput sampleBuffer: CMSampleBuffer, from connection: AVCaptureConnection) {
        guard let buffer = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }
        nonisolated(unsafe) let frame = buffer
        Task { @MainActor [weak self] in self?.onFrame?(frame) }
    }
}

#if DEBUG
/// Debug builds on the simulator (no camera) and UI tests: plays the e2e server's test
/// selfies (the same frames the web's fake camera uses), following the current shot.
@MainActor
final class FakeFrameSource: FrameSource {
    var onFrame: ((CVPixelBuffer) -> Void)?
    var previewLayer: AVCaptureVideoPreviewLayer? { nil }
    private(set) var latest: UIImage?
    private var frames: [CaptureShot: CVPixelBuffer] = [:]
    private var images: [CaptureShot: UIImage] = [:]
    private var shot: CaptureShot = .front
    private var timer: Timer?
    private let base: URL

    init(base: URL) { self.base = base }

    /// `-fake-frame front=blurry`: show another test frame for one shot (UI tests of rejections).
    private static func override(for shot: CaptureShot) -> String {
        let args = ProcessInfo.processInfo.arguments
        guard let i = args.firstIndex(of: "-fake-frame"), args.indices.contains(i + 1) else { return shot.rawValue }
        let parts = args[i + 1].split(separator: "=").map(String.init)
        return parts.count == 2 && parts[0] == shot.rawValue && ["front", "left", "right", "dark", "blurry"].contains(parts[1]) ? parts[1] : shot.rawValue
    }

    func start() async throws {
        for shot in CaptureShot.allCases {
            // The app's session (no URL cache): test frames stand in for selfies and must not
            // reach the disk either; the container test checks this.
            let (data, _) = try await NetworkSession.make().data(from: base.appending(path: "__e2e/selfie/\(Self.override(for: shot)).jpg"))
            guard let image = UIImage(data: data), let buffer = image.pixelBuffer() else { throw CameraError.unavailable }
            images[shot] = image
            frames[shot] = buffer
        }
        timer = Timer.scheduledTimer(withTimeInterval: 1.0 / 10, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.tick() }
        }
    }

    private func tick() {
        latest = images[shot]
        if let frame = frames[shot] { onFrame?(frame) }
    }

    func stop() { timer?.invalidate(); timer = nil }
    func setShot(_ shot: CaptureShot) { self.shot = shot }
}
#endif

extension UIImage {
    func pixelBuffer() -> CVPixelBuffer? {
        guard let cg = cgImage else { return nil }
        var buffer: CVPixelBuffer?
        let attrs = [kCVPixelBufferCGImageCompatibilityKey: true, kCVPixelBufferCGBitmapContextCompatibilityKey: true] as CFDictionary
        CVPixelBufferCreate(kCFAllocatorDefault, cg.width, cg.height, kCVPixelFormatType_32BGRA, attrs, &buffer)
        guard let buffer else { return nil }
        CVPixelBufferLockBaseAddress(buffer, [])
        defer { CVPixelBufferUnlockBaseAddress(buffer, []) }
        guard let ctx = CGContext(data: CVPixelBufferGetBaseAddress(buffer), width: cg.width, height: cg.height, bitsPerComponent: 8,
                                  bytesPerRow: CVPixelBufferGetBytesPerRow(buffer), space: CGColorSpaceCreateDeviceRGB(),
                                  bitmapInfo: CGImageAlphaInfo.premultipliedFirst.rawValue | CGBitmapInfo.byteOrder32Little.rawValue)
        else { return nil }
        ctx.draw(cg, in: CGRect(x: 0, y: 0, width: cg.width, height: cg.height))
        return buffer
    }
}
