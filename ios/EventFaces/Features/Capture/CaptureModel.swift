import CoreImage
import Foundation
import Observation
import SwiftUI
import UIKit

/// Guided three-shot capture → search. Frames and encoded shots exist only in memory and
/// are wiped as soon as they are sent (or the flow ends).
@MainActor
@Observable
final class CaptureModel {
    enum Phase: Equatable {
        case intro
        case starting
        case capturing(CaptureShot)
        case submitting
        /// Two server rejections in a row: tips instead of an endless retry loop (web QA-002).
        case paused
        case found(SearchResult)
        case queued
        case failed(Failure)
    }

    enum Failure: Equatable {
        case cameraDenied, cameraUnavailable, consentRequired, noAccess, busy, alreadyQueued, offline, server
    }

    private(set) var phase: Phase = .intro
    private(set) var guidance: Guidance = .noFace
    private(set) var rejection: (code: String, message: String, shot: String)?
    private(set) var manualAvailable = false
    private(set) var completed: [CaptureShot] = []
    private(set) var consecutiveRejections = 0

    let eventID: String
    let source: FrameSource
    private let service: EventService
    private var requirements: SelfieRequirements?
    private var captureToken: (value: String, issued: Date)?
    private var shots: [CaptureShot: Data] = [:]
    private var history: [CGPoint] = []
    private var okSince: Date?
    private var shotStarted = Date()
    private var analyzing = false
    private var frameCount = 0
    private var lastAnnouncement: (Guidance, Date)?
    private let ciContext = CIContext()

    static let manualAfter: TimeInterval = 8
    static let stableFor: TimeInterval = 0.6

    init(eventID: String, service: EventService, source: FrameSource) {
        self.eventID = eventID
        self.service = service
        self.source = source
    }

    var shotsDone: Int { completed.count }

    // MARK: Flow

    func start() async {
        phase = .starting
        do {
            requirements = try await service.selfieRequirements()
            try await newCaptureToken()
            source.onFrame = { [weak self] frame in self?.handle(frame) }
            try await source.start()
            begin(.front)
        } catch CameraError.denied {
            phase = .failed(.cameraDenied)
        } catch CameraError.unavailable {
            phase = .failed(.cameraUnavailable)
        } catch {
            phase = .failed(Self.failure(error))
        }
    }

    func stop() {
        source.stop()
        source.onFrame = nil
        wipe()
    }

    /// "Take this photo now": for when guidance can't settle (e.g. glasses glare).
    func captureNow() {
        guard case let .capturing(shot) = phase, let frame = latestFrame else { return }
        capture(frame, as: shot)
    }

    func retryAfterPause() async {
        consecutiveRejections = 0
        rejection = nil
        do {
            try await newCaptureToken()
            begin(next ?? .front)
        } catch {
            phase = .failed(Self.failure(error))
        }
    }

    private var next: CaptureShot? { CaptureShot.allCases.first { shots[$0] == nil } }

    private func begin(_ shot: CaptureShot) {
        phase = .capturing(shot)
        source.setShot(shot)
        history = []
        okSince = nil
        manualAvailable = false
        shotStarted = Date()
        guidance = .noFace
    }

    // MARK: Frames

    private var latestFrame: CVPixelBuffer?

    private func handle(_ frame: CVPixelBuffer) {
        latestFrame = frame
        guard case let .capturing(shot) = phase, let requirements, !analyzing else { return }
        frameCount += 1
        if frameCount % 2 != 0 { return }  // ~15 analyses/s is plenty
        analyzing = true
        nonisolated(unsafe) let buffer = frame
        Task.detached(priority: .userInitiated) {
            let measure = FaceAnalyzer.measure(buffer)
            await MainActor.run { self.apply(measure, frame: buffer, shot: shot, requirements: requirements) }
        }
    }

    private func apply(_ measure: FrameMeasure, frame: CVPixelBuffer, shot: CaptureShot, requirements: SelfieRequirements) {
        analyzing = false
        guard phase == .capturing(shot) else { return }
        manualAvailable = Date().timeIntervalSince(shotStarted) > Self.manualAfter
        let g = Guidance.evaluate(measure, shot: shot, requirements: requirements)
        if let c = measure.center { history = Array((history + [c]).suffix(8)) }
        let still = Guidance.isStill(history)
        guidance = g == .ok && !still ? .ok : g
        announce(guidance)
        if g == .ok && still {
            let since = okSince ?? Date()
            okSince = since
            if Date().timeIntervalSince(since) >= Self.stableFor { capture(frame, as: shot) }
        } else {
            okSince = nil
        }
    }

    private func capture(_ frame: CVPixelBuffer, as shot: CaptureShot) {
        guard let jpeg = jpeg(frame) else { return }
        shots[shot] = jpeg
        completed = CaptureShot.allCases.filter { shots[$0] != nil }
        UIImpactFeedbackGenerator(style: .medium).impactOccurred()
        if let next { begin(next) } else { Task { await submit() } }
    }

    private func jpeg(_ frame: CVPixelBuffer) -> Data? {
        // `AVCaptureVideoDataOutput` delivers buffers in the sensor's native (landscape)
        // orientation regardless of `connection.videoRotationAngle`: that property only
        // affects compatible display/encode consumers (preview layer, movie output), not
        // raw sample-buffer delegate callbacks. Rotate explicitly so the encoded JPEG is
        // actually portrait and upright — confirmed by real-device `selfie_quality` rows
        // showing width > height and ~90° roll before this fix. `.right` corrected the
        // aspect ratio but produced an upside-down face (`no_face`, confirmed live); `.left`
        // is the other 90° direction.
        let image = CIImage(cvPixelBuffer: frame).oriented(.left)
        // A fresh encode: no EXIF/GPS (the server re-encodes anyway).
        return ciContext.jpegRepresentation(of: image, colorSpace: CGColorSpace(name: CGColorSpace.sRGB)!,
                                            options: [kCGImageDestinationLossyCompressionQuality as CIImageRepresentationOption: 0.9])
    }

    // MARK: Submit

    private func newCaptureToken() async throws {
        captureToken = (try await service.captureToken(eventID: eventID), Date())
    }

    private func submit() async {
        phase = .submitting
        do {
            // Tokens live 60 s and are single-use: get a fresh one if this one is old.
            if let t = captureToken, Date().timeIntervalSince(t.issued) > 45 { try await newCaptureToken() }
            guard let token = captureToken?.value else { throw AppError.server(status: 0) }
            captureToken = nil
            let payload = CaptureShot.allCases.compactMap { s in shots[s].map { (name: s.rawValue, jpeg: $0) } }
            var outcome = try await service.search(eventID: eventID, captureToken: token, shots: payload)
            if outcome == .captureTokenInvalid {
                // Expired while the user was capturing: one retry with a fresh token.
                try await newCaptureToken()
                guard let fresh = captureToken?.value else { throw AppError.server(status: 0) }
                captureToken = nil
                outcome = try await service.search(eventID: eventID, captureToken: fresh, shots: payload)
            }
            handle(outcome)
        } catch {
            wipe()
            phase = .failed(Self.failure(error))
        }
    }

    private func handle(_ outcome: SearchOutcome) {
        switch outcome {
        case let .found(result):
            wipe()
            UINotificationFeedbackGenerator().notificationOccurred(.success)
            phase = .found(result)
        case .queued:
            wipe()
            phase = .queued
        case let .rejected(code, message, shot):
            UINotificationFeedbackGenerator().notificationOccurred(.error)
            consecutiveRejections += 1
            rejection = (code, message, shot)
            if let s = CaptureShot(rawValue: shot) { shots[s] = nil } else { shots.removeAll() }  // retake only that shot
            completed = CaptureShot.allCases.filter { shots[$0] != nil }
            if consecutiveRejections >= 2 {
                phase = .paused
            } else {
                Task {
                    do { try await newCaptureToken(); begin(next ?? .front) } catch { phase = .failed(Self.failure(error)) }
                }
            }
        case .busy:
            wipe()
            phase = .failed(.busy)
        case .alreadyQueued:
            wipe()
            phase = .failed(.alreadyQueued)
        case .consentRequired:
            wipe()
            phase = .failed(.consentRequired)
        case .captureTokenInvalid:
            wipe()
            phase = .failed(.server)
        }
    }

    #if DEBUG
    func testInject(shots: [String: Data]) {
        for (k, v) in shots { if let s = CaptureShot(rawValue: k) { self.shots[s] = v } }
        completed = CaptureShot.allCases.filter { self.shots[$0] != nil }
    }
    func testHandle(_ outcome: SearchOutcome) { handle(outcome) }
    #endif

    /// Drop every selfie byte we hold.
    private func wipe() {
        // Zero each buffer in place (one access per element; reading `shots` inside the
        // optional-chained mutation was an exclusivity violation that crashed).
        for key in Array(shots.keys) {
            shots[key]?.withUnsafeMutableBytes { _ = $0.initializeMemory(as: UInt8.self, repeating: 0) }
        }
        shots.removeAll()
        completed = []
        latestFrame = nil
        history = []
    }

    private func announce(_ g: Guidance) {
        let now = Date()
        if let (last, at) = lastAnnouncement, last == g || now.timeIntervalSince(at) < 2 { return }
        lastAnnouncement = (g, now)
        AccessibilityNotification.Announcement(String(localized: g.hintResource)).post()
    }

    static func failure(_ error: Error) -> Failure {
        switch error {
        case AppError.noAccess: .noAccess
        case AppError.consentRequired: .consentRequired
        case AppError.offline, is URLError: .offline
        default: .server
        }
    }
}

extension Guidance {
    var hintResource: LocalizedStringResource {
        switch self {
        case .ok: "Hold still"
        case .noFace: "Center your face in the oval"
        case .multipleFaces: "Make sure only you are in the picture"
        case .tooDark: "Too dark: face a window or lamp"
        case .tooBright: "Too bright: move out of direct light"
        case .moveCloser: "Move closer"
        case .moveBack: "Move back a little"
        case .raiseChin: "Raise your chin a little"
        case .lowerChin: "Lower your chin a little"
        case .keepHeadStraight: "Keep your head straight"
        case .turnBack: "Turn back toward the camera a little"
        case .lookStraight: "Face the camera"
        case .turnLeft: "Turn your head slightly to your left"
        case .turnRight: "Turn your head slightly to your right"
        }
    }
}
