import Foundation
import Testing
@testable import EventFaces

/// Organizer lite against the real e2e API: admin view, QR, moderation, members.
@Suite("Phase 6 integration (local e2e API)", .serialized, .enabled(if: ProcessInfo.processInfo.environment["EF_INTEGRATION"] == "1"))
@MainActor
struct Phase6IntegrationTests {
    let p2 = Phase2IntegrationTests()

    @Test func organizerSeesShareModerateAndRevoke() async throws {
        _ = try await p2.post("__e2e/reset")
        let event = try await p2.post("__e2e/event", query: [URLQueryItem(name: "guest_uploads", value: "true"), URLQueryItem(name: "moderation", value: "manual")])
        let eventID = try #require(event["id"] as? String), code = try #require(event["code"] as? String)

        // A guest uploads a photo (it waits for review).
        let (_, guest) = try await p2.signedIn("ios-guest-\(UUID().uuidString.prefix(6).lowercased())@example.com")
        _ = try await guest.join(code: code)
        let (photo, _) = try await TestNet.session.data(from: Phase2IntegrationTests.api.appending(path: "__e2e/guest-photo.jpg"))
        let ticket = try await guest.startUpload(eventID: eventID, filename: "g.jpg", contentType: "image/jpeg", size: photo.count)
        let file = try UploadManager.stage(photo, name: "g.jpg")
        try await UploadManager.shared.put(file: file, to: ticket.url, contentType: ticket.contentType) { _ in }
        _ = try await guest.completeUpload(eventID: eventID, photoID: ticket.photoID)

        // The guest can't use organizer endpoints (same rules as the web).
        await #expect(throws: AppError.noAccess) { _ = try await guest.admin(eventID) }

        let orgEmail = "ios-org-\(UUID().uuidString.prefix(6).lowercased())@example.com"
        _ = try await p2.post("__e2e/event/\(eventID)/organizer", query: [URLQueryItem(name: "email", value: orgEmail)])
        let (_, org) = try await p2.signedIn(orgEmail)

        let admin = try await org.admin(eventID)
        #expect(admin.accessCode == code)
        #expect(try await org.syncStatus(eventID).publishedPhotos >= 0)
        #expect(try await org.image(path: "/api/events/\(eventID)/qr?format=png").starts(with: [0x89, 0x50, 0x4E, 0x47]))

        var queue = [ModerationItem]()
        for _ in 0..<20 {  // ingest runs eagerly in the e2e server; give it a moment
            queue = try await org.moderationQueue(eventID)
            if queue.contains(where: { $0.id == ticket.photoID }) { break }
            try await Task.sleep(for: .milliseconds(300))
        }
        #expect(queue.contains { $0.id == ticket.photoID })
        try await org.moderate(eventID, photoID: ticket.photoID, approve: true)
        #expect(try await org.moderationQueue(eventID).contains { $0.id == ticket.photoID } == false)

        let members = try await org.members(eventID)
        let guestMember = try #require(members.first { $0.email.hasPrefix("ios-guest-") })
        try await org.revoke(eventID, userID: guestMember.userId)
        await #expect(throws: AppError.noAccess) { _ = try await guest.event(eventID) }  // revoked: out immediately
    }
}
