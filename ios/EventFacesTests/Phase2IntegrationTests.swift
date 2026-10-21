import Foundation
import OpenAPIURLSession
import Testing
import UIKit
@testable import EventFaces

/// Join, consent, capture analysis and search against the real e2e API (test data only).
@Suite("Phase 2 integration (local e2e API)", .serialized, .enabled(if: ProcessInfo.processInfo.environment["EF_INTEGRATION"] == "1"))
@MainActor
struct Phase2IntegrationTests {
    static let api = URL(string: "http://localhost:8000")!
    let config = AppConfig(apiBaseURL: api, appLinkHost: "localhost", appVersion: "1.0.0")

    func post(_ path: String, query: [URLQueryItem] = []) async throws -> [String: Any] {
        var r = URLRequest(url: Self.api.appending(path: path).appending(queryItems: query))
        r.httpMethod = "POST"
        let (data, _) = try await TestNet.session.data(for: r)
        return (try? JSONSerialization.jsonObject(with: data) as? [String: Any]) ?? [:]
    }

    func frame(_ name: String) async throws -> CVPixelBuffer {
        let (data, _) = try await TestNet.session.data(from: Self.api.appending(path: "__e2e/selfie/\(name).jpg"))
        return try #require(UIImage(data: data)?.pixelBuffer())
    }

    /// Sign in a fresh example.com account with the emailed code.
    func signedIn(_ email: String) async throws -> (AuthService, EventService) {
        let session = SessionManager(store: InMemorySecretStore())
        let auth = AuthService.make(session: session, config: config, transport: URLSessionTransport(configuration: .init(session: NetworkSession.make())))
        await auth.install()
        try await auth.requestCode(email: email)
        let (mail, _) = try await TestNet.session.data(from: Self.api.appending(path: "__e2e/mail").appending(queryItems: [URLQueryItem(name: "to", value: email)]))
        let subject = try #require((try JSONSerialization.jsonObject(with: mail) as? [String: String])?["subject"])
        _ = try await auth.verify(email: email, code: String(subject.prefix(6)), acceptedTerms: true)
        return (auth, EventService(api: auth.api, session: session, config: config, urlSession: NetworkSession.make()))
    }

    @Test func visionPoseMatchesTheServerConvention() async throws {
        // The e2e selfie set is one frame and its mirror: "left" has the server's largest
        // positive yaw (turned to THEIR left); "front" and "right" are the other frame.
        // Turned the way the simulator's fake camera turns them (the frames it plays).
        let upright = FakeFrameSource(base: Self.api).orientation
        let left = FaceAnalyzer.measure(try await frame("left"), orientation: upright)
        let right = FaceAnalyzer.measure(try await frame("right"), orientation: upright)
        #expect(left.faces == 1 && right.faces == 1, "Vision error: \(String(describing: FaceAnalyzer.lastError))")
        let (l, r) = (try #require(left.yaw), try #require(right.yaw))
        #expect(l > 0 && r < 0, "yaw left \(l) right \(r)")
        // And both pass the on-device guidance for their shot, like the server accepts them.
        #expect(Guidance.evaluate(left, shot: .left, requirements: requirements) == .ok)
        #expect(Guidance.evaluate(right, shot: .right, requirements: requirements) == .ok)
    }

    @Test func dimFramesAreCaughtBeforeUpload() async throws {
        let dark = FaceAnalyzer.measure(try await frame("dark"))
        #expect(Guidance.evaluate(dark, shot: .front, requirements: requirementsDefaults) == .tooDark || dark.faces == 0)
    }

    @Test func joinByCodeConsentAndSearchFindsYou() async throws {
        _ = try await post("__e2e/reset")
        let event = try await post("__e2e/event")
        let code = try #require(event["code"] as? String)
        let (_, events) = try await signedIn("ios-search-\(UUID().uuidString.prefix(6).lowercased())@example.com")

        await #expect(throws: JoinError.invalidCode) { _ = try await events.join(code: "WRONG123") }
        let joined = try await events.join(code: code.lowercased())
        #expect(joined.id == event["id"] as? String)

        // No consent yet: no capture token (the app routes to the consent screen).
        await #expect(throws: AppError.consentRequired) { _ = try await events.captureToken(eventID: joined.id) }
        let consent = try await events.consent()
        #expect(!consent.given && consent.text.sections.count == 4)
        _ = try await events.giveConsent(version: consent.version)

        var shots: [(name: String, jpeg: Data)] = []
        for name in ["front", "left", "right"] {
            let (data, _) = try await TestNet.session.data(from: Self.api.appending(path: "__e2e/selfie/\(name).jpg"))
            shots.append((name, data))
        }
        let token = try await events.captureToken(eventID: joined.id)
        let outcome = try await events.search(eventID: joined.id, captureToken: token, shots: shots)
        guard case let .found(result) = outcome else { Issue.record("expected matches, got \(outcome)"); return }
        #expect(!result.matches.isEmpty)
        // The capture token is single-use.
        #expect(try await events.search(eventID: joined.id, captureToken: token, shots: shots) == .captureTokenInvalid)
        #expect(try await events.myPhotos(eventID: joined.id).count == result.matches.count)
    }

    @Test func shortlistingAMatchedPhotoTogglesItInMyPhotos() async throws {
        _ = try await post("__e2e/reset")
        let event = try await post("__e2e/event")
        let code = try #require(event["code"] as? String)
        let (_, events) = try await signedIn("ios-shortlist-\(UUID().uuidString.prefix(6).lowercased())@example.com")
        let joined = try await events.join(code: code.lowercased())
        _ = try await events.giveConsent(version: try await events.consent().version)

        var shots: [(name: String, jpeg: Data)] = []
        for name in ["front", "left", "right"] {
            let (data, _) = try await TestNet.session.data(from: Self.api.appending(path: "__e2e/selfie/\(name).jpg"))
            shots.append((name, data))
        }
        let outcome = try await events.search(eventID: joined.id, captureToken: try await events.captureToken(eventID: joined.id), shots: shots)
        guard case let .found(result) = outcome else { Issue.record("expected matches, got \(outcome)"); return }
        let photoID = try #require(result.matches.first?.id)

        var photos = try await events.photos(eventID: joined.id)
        #expect(photos.first { $0.id == photoID }?.shortlisted == false)

        try await events.shortlist(eventID: joined.id, photoID: photoID, add: true)
        photos = try await events.photos(eventID: joined.id)
        #expect(photos.first { $0.id == photoID }?.shortlisted == true)

        try await events.shortlist(eventID: joined.id, photoID: photoID, add: false)
        photos = try await events.photos(eventID: joined.id)
        #expect(photos.first { $0.id == photoID }?.shortlisted == false)
    }

    @Test func organizerAddedVideosAreListedForAttendees() async throws {
        _ = try await post("__e2e/reset")
        let event = try await post("__e2e/event")
        let eventID = try #require(event["id"] as? String)
        let orgEmail = "ios-organizer-\(UUID().uuidString.prefix(6).lowercased())@example.com"
        _ = try await post("__e2e/event/\(eventID)/organizer", query: [URLQueryItem(name: "email", value: orgEmail)])
        let (_, organizer) = try await signedIn(orgEmail)

        let (_, attendee) = try await signedIn("ios-attendee-\(UUID().uuidString.prefix(6).lowercased())@example.com")
        _ = try await attendee.join(code: try #require(event["code"] as? String))

        #expect(try await attendee.videos(eventID: eventID).isEmpty)

        _ = try await organizer.api.eventsAddEventVideo(
            path: .init(eventId: eventID),
            body: .json(.init(title: "Highlights", url: "https://youtu.be/dQw4w9WgXcQ"))
        )
        let videos = try await attendee.videos(eventID: eventID)
        #expect(videos.count == 1 && videos[0].title == "Highlights" && videos[0].provider == "youtube")
    }

    @Test func aBlurrySelfieIsRejectedWithItsReason() async throws {
        _ = try await post("__e2e/reset")
        let event = try await post("__e2e/event")
        let (_, events) = try await signedIn("ios-blur-\(UUID().uuidString.prefix(6).lowercased())@example.com")
        let joined = try await events.join(code: try #require(event["code"] as? String))
        _ = try await events.giveConsent(version: try await events.consent().version)
        var shots: [(name: String, jpeg: Data)] = []
        for (shot, file) in [("front", "blurry"), ("left", "left"), ("right", "right")] {
            let (data, _) = try await TestNet.session.data(from: Self.api.appending(path: "__e2e/selfie/\(file).jpg"))
            shots.append((shot, data))
        }
        let outcome = try await events.search(eventID: joined.id, captureToken: try await events.captureToken(eventID: joined.id), shots: shots)
        guard case let .rejected(code, _, shot) = outcome else { Issue.record("expected a rejection, got \(outcome)"); return }
        #expect(shot == "front" && RejectionMessages.keys[code] != nil)
    }

    var requirementsDefaults: SelfieRequirements { requirements }
}
