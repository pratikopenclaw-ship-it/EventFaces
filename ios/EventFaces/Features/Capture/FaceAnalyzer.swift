import CoreVideo
import Foundation
import CoreML
import Vision

/// Vision face analysis for live guidance. Runs on frames in memory only.
enum FaceAnalyzer {
    nonisolated(unsafe) static var lastError: Error?
    /// Vision's yaw sign relative to the server's convention, calibrated against the server
    /// on the same frames (Phase2IntegrationTests, the e2e selfies): the server's "left"
    /// frame (largest positive yaw) measures +7.8° in Vision, its front/right frame -8.4°.
    static let yawSign: Double = 1
    /// Pitch and roll only gate on |value|, so their signs don't change any decision.
    static let pitchSign: Double = 1

    static func measure(_ buffer: CVPixelBuffer) -> FrameMeasure {
        let request = VNDetectFaceRectanglesRequest()
        request.revision = VNDetectFaceRectanglesRequestRevision3
        #if targetEnvironment(simulator)
        // The simulator has no GPU/Neural Engine inference context for Vision's face model.
        if let cpu = MLComputeDevice.allComputeDevices.first(where: { if case .cpu = $0 { true } else { false } }) {
            request.setComputeDevice(cpu, for: .main)
        }
        #endif
        let handler = VNImageRequestHandler(cvPixelBuffer: buffer, orientation: .up)
        do {
            try handler.perform([request])
        } catch {
            lastError = error  // diagnostics only (never logged with frame data)
        }
        let faces = request.results ?? []
        guard let face = faces.max(by: { $0.boundingBox.height < $1.boundingBox.height }) else {
            return FrameMeasure(faces: 0)
        }
        let box = face.boundingBox  // normalized, origin bottom-left
        let deg = { (v: NSNumber?) in v.map { $0.doubleValue * 180 / .pi } }
        return FrameMeasure(
            faces: faces.filter { $0.boundingBox.height > box.height * 0.5 }.count,  // ignore tiny background faces
            yaw: deg(face.yaw).map { $0 * yawSign },
            pitch: deg(face.pitch).map { $0 * pitchSign } ?? 0,
            roll: deg(face.roll) ?? 0,
            faceHeightRatio: Double(box.height) * 1.1,  // Vision's box is a bit tighter than the server detector's
            brightness: meanLuma(buffer, in: box),
            center: CGPoint(x: box.midX, y: box.midY)
        )
    }

    /// Mean luma of the face region (sparse sampling; cheap enough per frame).
    static func meanLuma(_ buffer: CVPixelBuffer, in box: CGRect) -> Double? {
        CVPixelBufferLockBaseAddress(buffer, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(buffer, .readOnly) }
        guard CVPixelBufferGetPixelFormatType(buffer) == kCVPixelFormatType_32BGRA,
              let base = CVPixelBufferGetBaseAddress(buffer)?.assumingMemoryBound(to: UInt8.self) else { return nil }
        let w = CVPixelBufferGetWidth(buffer), h = CVPixelBufferGetHeight(buffer), row = CVPixelBufferGetBytesPerRow(buffer)
        let x0 = max(0, Int(box.minX * CGFloat(w))), x1 = min(w - 1, Int(box.maxX * CGFloat(w)))
        let y0 = max(0, Int((1 - box.maxY) * CGFloat(h))), y1 = min(h - 1, Int((1 - box.minY) * CGFloat(h)))
        guard x1 > x0, y1 > y0 else { return nil }
        let step = max(1, (x1 - x0) / 32)
        var sum = 0.0, n = 0.0
        for y in stride(from: y0, to: y1, by: step) {
            for x in stride(from: x0, to: x1, by: step) {
                let p = base + y * row + x * 4
                sum += 0.114 * Double(p[0]) + 0.587 * Double(p[1]) + 0.299 * Double(p[2])  // BGRA
                n += 1
            }
        }
        return n > 0 ? sum / n : nil
    }
}
