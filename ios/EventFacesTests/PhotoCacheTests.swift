import Foundation
import Testing
import UIKit
@testable import EventFaces

@Suite("Photo cache", .serialized)
struct PhotoCacheTests {
    let root = FileManager.default.temporaryDirectory.appending(path: "cache-tests-\(UUID().uuidString)")
    var cache: PhotoCache { PhotoCache(root: root) }

    func jpeg(_ size: CGSize) -> Data {
        UIGraphicsImageRenderer(size: size, format: { let f = UIGraphicsImageRendererFormat(); f.scale = 1; return f }()).jpegData(withCompressionQuality: 0.9) { ctx in
            UIColor.systemTeal.setFill()
            ctx.fill(CGRect(origin: .zero, size: size))
        }
    }

    @Test func filesAreProtectedAndNotBackedUp() async throws {
        let cache = self.cache
        _ = try await cache.store(jpeg(CGSize(width: 800, height: 600)), event: "e1", photo: "p1", variant: "thumb", maxPixel: 200)
        let url = await cache.fileURL(event: "e1", photo: "p1", variant: "thumb")
        let values = try url.resourceValues(forKeys: [.isExcludedFromBackupKey])
        #expect(values.isExcludedFromBackup == true)
        let attrs = try FileManager.default.attributesOfItem(atPath: url.path)
        #if targetEnvironment(simulator)
        // The simulator doesn't enforce Data Protection; the attribute is what we can check.
        #expect(attrs[.protectionKey] as? FileProtectionType == .completeUntilFirstUserAuthentication || attrs[.protectionKey] == nil)
        #else
        #expect(attrs[.protectionKey] as? FileProtectionType == .completeUntilFirstUserAuthentication)
        #endif
        try? FileManager.default.removeItem(at: root)
    }

    @Test func gridImagesAreDownsampledNotFullResolution() async throws {
        let image = try #require(try await cache.store(jpeg(CGSize(width: 4000, height: 3000)), event: "e", photo: "big", variant: "preview", maxPixel: 300))
        #expect(max(image.size.width * image.scale, image.size.height * image.scale) <= 300)
        try? FileManager.default.removeItem(at: root)
    }

    @Test func purgeAndKeepOnly() async throws {
        let cache = self.cache
        for p in ["3f2504e0-4f89-11d3-9a0c-0305e82c3301", "3f2504e0-4f89-11d3-9a0c-0305e82c3302"] {
            _ = try await cache.store(jpeg(CGSize(width: 50, height: 50)), event: "ev", photo: p, variant: "thumb", maxPixel: 50)
        }
        await cache.keepOnly(event: "ev", photos: ["3f2504e0-4f89-11d3-9a0c-0305e82c3301"])
        #expect(FileManager.default.fileExists(atPath: await cache.fileURL(event: "ev", photo: "3f2504e0-4f89-11d3-9a0c-0305e82c3301", variant: "thumb").path))
        #expect(!FileManager.default.fileExists(atPath: await cache.fileURL(event: "ev", photo: "3f2504e0-4f89-11d3-9a0c-0305e82c3302", variant: "thumb").path))
        await cache.purge(event: "ev")
        #expect(await cache.image(event: "ev", photo: "3f2504e0-4f89-11d3-9a0c-0305e82c3301", variant: "thumb", maxPixel: 50) == nil)
        _ = try await cache.store(jpeg(CGSize(width: 50, height: 50)), event: "other", photo: "x", variant: "thumb", maxPixel: 50)
        await cache.purgeAll()
        #expect(!FileManager.default.fileExists(atPath: root.path))
    }

    @Test(arguments: ["../../etc/passwd", "a/b", "..", "x\u{0}y"])
    func idsCannotEscapeTheCacheFolder(_ id: String) async {
        let url = await cache.fileURL(event: id, photo: id, variant: id)
        #expect(url.standardizedFileURL.path.hasPrefix(root.standardizedFileURL.path))
        #expect(!url.path.contains(".."))
    }
}

@MainActor
@Suite("Results model")
struct ResultsModelTests {
    let transport = FakeTransport()

    func model() -> ResultsModel {
        let session = SessionManager(store: InMemorySecretStore(), signerLoader: { _ in TestSigner() })
        let auth = AuthService.make(session: session, config: testConfig, transport: transport)
        let events = EventService(api: auth.api, session: session, config: testConfig, urlSession: NetworkSession.make())
        return ResultsModel(eventID: "3f2504e0-4f89-11d3-9a0c-0305e82c3301", service: events, session: session, config: testConfig)
    }

    nonisolated static let photosJSON = #"""
    [{"id":"aaaaaaaa-0000-0000-0000-000000000001","width":10,"height":10,"similarity":0.9,"tier":"best","verdict":null,"expires_at":null},
     {"id":"aaaaaaaa-0000-0000-0000-000000000002","width":10,"height":10,"similarity":0.5,"tier":"possible","verdict":null,"expires_at":null},
     {"id":"aaaaaaaa-0000-0000-0000-000000000003","width":10,"height":10,"similarity":null,"tier":null,"verdict":null,"expires_at":null}]
    """#

    @Test func sectionsFollowTheTiers() async {
        transport.handler = { _, _ in (200, Self.photosJSON) }
        let m = model()
        await m.load()
        #expect(m.photos(in: .best).map(\.id) == ["aaaaaaaa-0000-0000-0000-000000000001"])
        #expect(m.photos(in: .possible).count == 1 && m.photos(in: .uploads).count == 1)
        #expect(m.ordered.map(\.id).last == "aaaaaaaa-0000-0000-0000-000000000003")
    }

    @Test func notMeRemovesThePhoto() async {
        transport.handler = { req, _ in req.path?.hasSuffix("/feedback") == true ? (204, "") : (200, Self.photosJSON) }
        let m = model()
        await m.load()
        await m.verdict(m.photos[1], isMe: false)
        #expect(m.photos.count == 2 && !m.photos.contains { $0.id == "aaaaaaaa-0000-0000-0000-000000000002" })
        await m.verdict(m.photos[0], isMe: true)
        #expect(m.photos[0].verdict == .me)
    }

    @Test func lostAccessClearsEverything() async {
        transport.handler = { _, _ in (403, #"{"detail":"You don't have access to this event"}"#) }
        let m = model()
        await m.load()
        #expect(m.noAccess && m.photos.isEmpty)
    }

    @Test func matchCountExcludesOwnUploads() async {
        // best + possible count toward the headline; the plain upload (tier nil) doesn't.
        transport.handler = { _, _ in (200, Self.photosJSON) }
        let m = model()
        await m.load()
        #expect(m.matchCount == 2)
    }
}

@Suite("Justified grid aspect ratio (same clamp as the web)")
struct JustifiedRatioTests {
    func photo(width: Int?, height: Int?) -> MyPhoto {
        let json = #"{"id":"aaaaaaaa-0000-0000-0000-000000000001","width":\#(width.map(String.init) ?? "null"),"height":\#(height.map(String.init) ?? "null")}"#
        return try! JSONDecoder.api.decode(MyPhoto.self, from: Data(json.utf8))
    }

    @Test func usesTheServersWidthAndHeight() {
        #expect(ResultsView.ratio(photo(width: 16, height: 9)) == CGFloat(16) / CGFloat(9))
    }

    @Test func clampsExtremeRatios() {
        #expect(ResultsView.ratio(photo(width: 100, height: 1)) == 2.5)
        #expect(ResultsView.ratio(photo(width: 1, height: 100)) == 0.5)
    }

    @Test func defaultsTo4By3WhenDimensionsAreMissing() {
        #expect(ResultsView.ratio(photo(width: nil, height: nil)) == 4.0 / 3.0)
        #expect(ResultsView.ratio(photo(width: 10, height: 0)) == 4.0 / 3.0)
    }
}
