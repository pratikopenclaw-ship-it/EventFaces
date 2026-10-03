import CoreGraphics
import Foundation
import Testing
@testable import EventFaces

let requirements = SelfieRequirements(
    captureTokenSeconds: 60, faceHeightMax: 0.6, faceHeightMin: 0.3, frontMaxYaw: 12, globalFileUpload: false,
    maxBrightness: 210, maxPitch: 15, maxRoll: 15, maxYaw: 20, minBrightness: 60, minHeight: 480, minWidth: 640, sideMinYaw: 5
)

func measure(faces: Int = 1, yaw: Double = 0, pitch: Double = 0, roll: Double = 0, ratio: Double = 0.45, brightness: Double = 120) -> FrameMeasure {
    FrameMeasure(faces: faces, yaw: yaw, pitch: pitch, roll: roll, faceHeightRatio: ratio, brightness: brightness, center: .zero)
}

@Suite("Guidance (same rules and order as the web)")
struct GuidanceTests {
    @Test(arguments: [
        (measure(faces: 0), CaptureShot.front, Guidance.noFace),
        (measure(faces: 2), .front, .multipleFaces),
        (measure(brightness: 40), .front, .tooDark),
        (measure(brightness: 230), .front, .tooBright),
        (measure(ratio: 0.2), .front, .moveCloser),
        (measure(ratio: 0.7), .front, .moveBack),
        (measure(pitch: -20), .front, .raiseChin),  // pitch < 0 = looking down
        (measure(pitch: 20), .front, .lowerChin),
        (measure(roll: 20), .front, .keepHeadStraight),
        (measure(yaw: 25), .front, .turnBack),
        (measure(yaw: 14), .front, .lookStraight),
        (measure(yaw: 2), .left, .turnLeft),  // yaw > 0 = turned to THEIR left
        (measure(yaw: -9), .left, .turnLeft),
        (measure(yaw: 9), .left, .ok),
        (measure(yaw: 9), .right, .turnRight),
        (measure(yaw: -9), .right, .ok),
        (measure(), .front, .ok),
    ] as [(FrameMeasure, CaptureShot, Guidance)])
    func rule(m: FrameMeasure, shot: CaptureShot, expected: Guidance) {
        #expect(Guidance.evaluate(m, shot: shot, requirements: requirements) == expected)
    }

    @Test func earlierProblemsWinLikeOnTheWeb() {
        // Too dark and too far: light first (the web's order).
        #expect(Guidance.evaluate(measure(ratio: 0.1, brightness: 10), shot: .front, requirements: requirements) == .tooDark)
    }

    @Test func stillnessNeedsSixSteadyFrames() {
        let steady = Array(repeating: CGPoint(x: 0.5, y: 0.5), count: 6)
        #expect(Guidance.isStill(steady))
        #expect(!Guidance.isStill(Array(steady.prefix(5))))
        #expect(!Guidance.isStill(steady + [CGPoint(x: 0.55, y: 0.5)]))
    }
}

@Suite("Per-event accent (same rule as the web)")
struct EventAccentTests {
    @Test(arguments: ["#0F766E", "#FFFF00", "#FFFFFF", "#000000", "#808080", "#FF00FF", "#00FFFF", "#1E3A8A", "#F97316", "#7DD3FC", "#B91C1C", "#22C55E"])
    func readableInBothThemes(hex: String) throws {
        for scheme in [EventAccent.ColorSchemeKey.light, .dark] {
            let pair = try #require(EventAccent.readable(hex, for: scheme))
            let accent = try #require(EventAccent.rgb(pair.accent))
            for surface in EventAccent.surfaces[scheme]! {
                #expect(EventAccent.contrast(accent, EventAccent.rgb(surface)!) >= 4.5, "\(hex) \(scheme) on \(surface)")
            }
            #expect(EventAccent.contrast(EventAccent.rgb(pair.onAccent)!, accent) >= 4.5)
        }
    }

    @Test func surfacesMatchTheSharedTokens() throws {
        let tokens = try #require(try JSONSerialization.jsonObject(with: Data(contentsOf: repoRoot.appending(path: "design/tokens.json"))) as? [String: Any])
        for (scheme, key) in [(EventAccent.ColorSchemeKey.light, "light"), (.dark, "dark")] {
            let t = try #require(tokens[key] as? [String: String])
            #expect(EventAccent.surfaces[scheme] == [t["surface"]!, t["bg"]!, t["surface-2"]!].map { $0.uppercased() })
        }
    }

    @Test func malformedColoursAreIgnored() {
        for bad in ["red", "#fff", "url(x)", "#12345G", ""] { #expect(EventAccent.color(bad) == nil) }
    }
}

@Suite("Rejection messages")
struct RejectionMessageTests {
    @Test func everyServerReasonHasALocalizedMessage() throws {
        let source = try String(contentsOf: repoRoot.appending(path: "backend/app/services/selfie_quality.py"), encoding: .utf8)
        let block = try #require(source.components(separatedBy: "MESSAGES: dict[str, str] = {").last?.components(separatedBy: "}").first)
        let codes = block.matches(of: /"([a-z_]+)":/).map { String($0.1) }
        #expect(!codes.isEmpty)
        #expect(Set(codes).subtracting(RejectionMessages.keys.keys).isEmpty, "add these to RejectionMessages: \(Set(codes).subtracting(RejectionMessages.keys.keys))")
    }
}

@Suite("Event service error mapping")
struct EventServiceMappingTests {
    func service(_ transport: FakeTransport) -> EventService {
        let session = SessionManager(store: InMemorySecretStore(), signerLoader: { _ in TestSigner() })
        let auth = AuthService.make(session: session, config: testConfig, transport: transport)
        return EventService(api: auth.api, session: session, config: testConfig, urlSession: NetworkSession.make())
    }

    @Test func consentRequiredIsNotNoAccess() async {
        let t = FakeTransport()
        t.handler = { _, _ in (403, #"{"detail":"consent_required"}"#) }
        await #expect(throws: AppError.consentRequired) { _ = try await service(t).captureToken(eventID: "e") }
        t.handler = { req, _ in
            req.path == "/api/me/face-consent" ? (200, consentJSON(given: true)) : (403, #"{"detail":"You don't have access to this event"}"#)
        }
        await #expect(throws: AppError.noAccess) { _ = try await service(t).captureToken(eventID: "e") }
        // Body unreadable: the consent endpoint decides.
        t.handler = { req, _ in req.path == "/api/me/face-consent" ? (200, consentJSON(given: false)) : (403, "") }
        await #expect(throws: AppError.consentRequired) { _ = try await service(t).captureToken(eventID: "e") }
    }
}

func consentJSON(given: Bool) -> String {
    #"{"version":"2026-09-30","grant_days":7,"given":\#(given),"text":{"locale":"en","title":"t","intro":"i","sections":[],"agreement":"a","action":"c"}}"#
}

@MainActor
@Suite("Capture model")
struct CaptureModelTests {
    /// Regression: wiping the captured selfies crashed (exclusivity violation) after every
    /// search. Drive a search outcome and the wipe through the model.
    @Test func wipingSelfiesAfterASearchDoesNotCrash() async {
        let transport = FakeTransport()
        transport.handler = { req, _ in
            if req.path?.hasSuffix("/capture-token") == true { return (200, #"{"token":"t","expires_in":60}"#) }
            return (200, "{}")
        }
        let session = SessionManager(store: InMemorySecretStore(), signerLoader: { _ in TestSigner() })
        let auth = AuthService.make(session: session, config: testConfig, transport: transport)
        let service = EventService(api: auth.api, session: session, config: testConfig, urlSession: NetworkSession.make())
        let model = CaptureModel(eventID: "e", service: service, source: NullSource())
        model.testInject(shots: ["front": Data(repeating: 7, count: 1024), "left": Data(repeating: 7, count: 1024)])
        model.testHandle(.queued)
        #expect(model.phase == .queued && model.completed.isEmpty)
    }
}

@MainActor
final class NullSource: FrameSource {
    var onFrame: ((CVPixelBuffer) -> Void)?
    var previewLayer: AVCaptureVideoPreviewLayer? { nil }
    func start() async throws {}
    func stop() {}
    func setShot(_ shot: CaptureShot) {}
}

import AVFoundation
