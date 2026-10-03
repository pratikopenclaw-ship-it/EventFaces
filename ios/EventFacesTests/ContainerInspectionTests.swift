import Foundation
import Testing
import UIKit
@testable import EventFaces

/// "Selfie frames live in memory only": after a real search (and loading the results),
/// the app's container must hold no trace of the selfies. Every file the search created
/// must be a downloaded event photo in the photo cache, protected and excluded from backup.
@Suite("Container after a search (local e2e API)", .serialized, .enabled(if: ProcessInfo.processInfo.environment["EF_INTEGRATION"] == "1"))
@MainActor
struct ContainerInspectionTests {
    let phase2 = Phase2IntegrationTests()

    static func files() -> [URL: Date] {
        let home = URL(fileURLWithPath: NSHomeDirectory())
        var out: [URL: Date] = [:]
        let keys: [URLResourceKey] = [.isRegularFileKey, .contentModificationDateKey]
        guard let walker = FileManager.default.enumerator(at: home, includingPropertiesForKeys: keys) else { return out }
        for case let url as URL in walker {
            guard let values = try? url.resourceValues(forKeys: Set(keys)), values.isRegularFile == true else { continue }
            out[url.standardizedFileURL] = values.contentModificationDate ?? .distantPast
        }
        return out
    }

    /// Distinctive slices of each selfie: if any file contains one, a selfie (or a copy of
    /// its encoded bytes) reached the disk.
    static func fingerprints(_ jpeg: Data) -> [Data] {
        stride(from: jpeg.count / 4, to: jpeg.count - 64, by: jpeg.count / 4).map { jpeg.subdata(in: $0 ..< $0 + 64) }
    }

    @Test func aSearchLeavesNoSelfieOnDisk() async throws {
        _ = try await phase2.post("__e2e/reset")
        let event = try await phase2.post("__e2e/event")
        let code = try #require(event["code"] as? String)
        let (auth, events) = try await phase2.signedIn("ios-container-\(UUID().uuidString.prefix(6).lowercased())@example.com")
        let joined = try await events.join(code: code)
        _ = try await events.giveConsent(version: try await events.consent().version)

        var shots: [(name: String, jpeg: Data)] = []
        for name in ["front", "left", "right"] {
            let (data, _) = try await TestNet.session.data(from: Phase2IntegrationTests.api.appending(path: "__e2e/selfie/\(name).jpg"))
            shots.append((name, data))
        }
        let before = Self.files()
        let started = Date()
        // The simulator's fake camera loads its test frames over the network: they must not
        // be cached on disk either (they stand in for selfies).
        let camera = FakeFrameSource(base: Phase2IntegrationTests.api)
        try await camera.start()
        camera.stop()
        let outcome = try await events.search(eventID: joined.id, captureToken: try await events.captureToken(eventID: joined.id), shots: shots)
        guard case let .found(result) = outcome else { Issue.record("expected matches, got \(outcome)"); return }
        // Load the results like the gallery does (this is what may legitimately touch disk).
        #expect(!result.matches.isEmpty)
        for photo in try await events.photos(eventID: joined.id).prefix(3) {
            _ = try await events.cachedImage(eventID: joined.id, photoID: photo.id, variant: "thumb", maxPixel: 360)
        }

        let after = Self.files()
        let cacheRoot = await PhotoCache.shared.root.standardizedFileURL.path
        let changed = after.filter { url, modified in before[url] == nil || modified >= started }.map(\.key)
        for url in changed {
            #expect(url.path.hasPrefix(cacheRoot) || url.path.contains("/Library/Preferences/"), "unexpected file after a search: \(url.lastPathComponent)")
            if url.path.hasPrefix(cacheRoot) {
                let values = try url.resourceValues(forKeys: [.isExcludedFromBackupKey, .fileProtectionKey])
                #expect(values.isExcludedFromBackup == true)
                #expect(values.fileProtection == .completeUntilFirstUserAuthentication)
            }
        }
        // No file anywhere in the container contains selfie bytes.
        let prints = shots.flatMap { Self.fingerprints($0.jpeg) }
        for url in after.keys {
            guard let data = try? Data(contentsOf: url, options: .mappedIfSafe) else { continue }
            for print in prints {
                #expect(data.range(of: print) == nil, "selfie bytes found in \(url.lastPathComponent)")
            }
        }
        await auth.signOut()
    }
}
