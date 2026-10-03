import Foundation
import Testing
@testable import EventFaces

@Suite("Upload content types")
struct UploadTypeTests {
    @Test func magicBytesDecideTheType() {
        #expect(UploadView.contentType(Data([0xFF, 0xD8, 0xFF, 0xE0])) == "image/jpeg")
        #expect(UploadView.contentType(Data([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A])) == "image/png")
        #expect(UploadView.contentType(Data([0, 0, 0, 0x18] + Array("ftypheic".utf8))) == "image/heic")
        #expect(UploadView.contentType(Data("GIF89a......".utf8)) == nil)
        #expect(UploadView.contentType(Data("<svg>".utf8)) == nil)
    }
}

/// Guest upload end to end against the e2e API and local storage (SeaweedFS).
@Suite("Phase 5 integration (local e2e API)", .serialized, .enabled(if: ProcessInfo.processInfo.environment["EF_INTEGRATION"] == "1"))
@MainActor
struct Phase5IntegrationTests {
    let p2 = Phase2IntegrationTests()

    @Test func uploadWaitsForApproval() async throws {
        _ = try await p2.post("__e2e/reset")
        let event = try await p2.post("__e2e/event", query: [URLQueryItem(name: "guest_uploads", value: "true"), URLQueryItem(name: "moderation", value: "manual")])
        let (_, events) = try await p2.signedIn("ios-up-\(UUID().uuidString.prefix(6).lowercased())@example.com")
        let joined = try await events.join(code: try #require(event["code"] as? String))
        #expect(joined.guestUploadEnabled && (joined.uploadMaxBytes ?? 0) > 0)

        let (photo, _) = try await TestNet.session.data(from: Phase2IntegrationTests.api.appending(path: "__e2e/guest-photo.jpg"))
        let ticket = try await events.startUpload(eventID: joined.id, filename: "photo.jpg", contentType: "image/jpeg", size: photo.count)
        // Only the storage host, never the API host, gets the bytes (the presigned URL is the credential).
        #expect(ticket.url.host() != nil)
        let file = try UploadManager.stage(photo, name: "photo.jpg")
        defer { try? FileManager.default.removeItem(at: file) }
        let progress = ProgressLog()
        try await UploadManager.shared.put(file: file, to: ticket.url, contentType: ticket.contentType) { progress.add($0) }
        let done = try await events.completeUpload(eventID: joined.id, photoID: ticket.photoID)
        #expect(done.status == .pendingReview)  // manual moderation: invisible until approved
        #expect(try await events.myUploads(eventID: joined.id).map(\.id).contains(ticket.photoID))
        #expect(try await events.photos(eventID: joined.id).contains { $0.id == ticket.photoID } == false)
    }

    @Test func wrongDeclaredSizeIsRefusedByStorage() async throws {
        _ = try await p2.post("__e2e/reset")
        let event = try await p2.post("__e2e/event", query: [URLQueryItem(name: "guest_uploads", value: "true")])
        let (_, events) = try await p2.signedIn("ios-up2-\(UUID().uuidString.prefix(6).lowercased())@example.com")
        let joined = try await events.join(code: try #require(event["code"] as? String))
        let ticket = try await events.startUpload(eventID: joined.id, filename: "p.jpg", contentType: "image/jpeg", size: 1000)
        let file = try UploadManager.stage(Data(repeating: 0xFF, count: 5000), name: "p.jpg")
        defer { try? FileManager.default.removeItem(at: file) }
        await #expect(throws: (any Error).self) {
            try await UploadManager.shared.put(file: file, to: ticket.url, contentType: ticket.contentType) { _ in }
        }
    }
}

final class ProgressLog: @unchecked Sendable {
    private let lock = NSLock()
    private var values: [Double] = []
    func add(_ v: Double) { lock.withLock { values.append(v) } }
}
