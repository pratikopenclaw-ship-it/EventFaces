import Foundation
import OpenAPIURLSession
import Testing
@testable import EventFaces

@Suite("Push payloads")
struct PushRouteTests {
    let event = "3F2504E0-4F89-11D3-9A0C-0305E82C3301"

    @Test func knownKindsRoute() {
        #expect(PushRoute.parse(["kind": "search_ready", "event_id": event]) == .searchResults(eventID: event.lowercased()))
        #expect(PushRoute.parse(["kind": "search_rejected", "event_id": event]) == .searchRejected(eventID: event.lowercased()))
    }

    @Test func malformedPayloadsAreIgnored() {
        let id = "3F2504E0-4F89-11D3-9A0C-0305E82C3301"
        let payloads: [[AnyHashable: Any]] = [
            [:],
            ["kind": "search_ready"],
            ["event_id": id],
            ["kind": "open_url", "event_id": id],
            ["kind": "search_ready", "event_id": "../../admin"],
            ["kind": "search_ready", "event_id": "3F2504E04F8911D39A0C0305E82C3301"],
            ["kind": "search_ready", "event_id": 42],
            ["kind": ["search_ready"], "event_id": id],
            // Organizer-only; the iOS app is attendee-only, so the backend may still send
            // this kind but it must stay unroutable here.
            ["kind": "moderation_pending", "event_id": id],
        ]
        for payload in payloads { #expect(PushRoute.parse(payload) == nil, "\(payload)") }
    }

    @Test func tokenHexAndEnvironment() {
        #expect(PushToken.hex(Data([0x00, 0xAB, 0x10])) == "00ab10")
        #if DEBUG
        #expect(PushToken.environment == "sandbox")
        #endif
    }
}

@MainActor
@Suite("Account state")
struct AccountStateTests {
    @Test func appLockIsOffByDefault() throws {
        let defaults = try #require(UserDefaults(suiteName: "lock-\(UUID().uuidString)"))
        let lock = AppLock(defaults: defaults)
        #expect(!lock.enabled && !lock.locked)
        lock.didEnterBackground()
        #expect(!lock.locked)
    }

    @Test func deletingTheAccountLeavesNothingBehind() async throws {
        let store = InMemorySecretStore()
        try store.set(Data("r".utf8), for: "refresh-token")
        let session = SessionManager(store: store, signerLoader: { _ in TestSigner() })
        let defaults = try #require(UserDefaults(suiteName: "delete-\(UUID().uuidString)"))
        let model = AppModel(auth: .make(session: session, config: testConfig, transport: FakeTransport()), config: testConfig, defaults: defaults)
        _ = try await PhotoCache.shared.store(Data(base64Encoded: "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAMCAgICAgMCAgIDAwMDBAYEBAQEBAgGBgUGCQgKCgkICQkKDA8MCgsOCwkJDRENDg8QEBEQCgwSExIQEw8QEBD/yQALCAABAAEBAREA/8wABgAQEAX/2gAIAQEAAD8A0s8g/9k=")!, event: "e", photo: "p", variant: "thumb", maxPixel: 10)
        await model.didDeleteAccount()
        #expect(store.isEmpty)
        #expect(model.account == .signedOut && model.notice == .accountDeleted)
        #expect(!FileManager.default.fileExists(atPath: await PhotoCache.shared.root.path))
    }

    @Test func aResultsNotificationOpensThatEventsResults() throws {
        let defaults = try #require(UserDefaults(suiteName: "route-\(UUID().uuidString)"))
        let model = AppModel(auth: .make(session: SessionManager(store: InMemorySecretStore()), config: testConfig, transport: FakeTransport()), config: testConfig, defaults: defaults)
        model.handle(.searchResults(eventID: "e1"))
        #expect(model.path.isEmpty)  // signed out: ignored
        let user = try JSONDecoder.api.decode(User.self, from: Data(userJSON().utf8))
        model.didSignIn(user)
        model.handle(.searchResults(eventID: "e1"))
        #expect(model.path == ["e1"] && model.openResultsFor == "e1")
    }
}

/// Account, devices and privacy against the real e2e API.
@Suite("Phase 4 integration (local e2e API)", .serialized, .enabled(if: ProcessInfo.processInfo.environment["EF_INTEGRATION"] == "1"))
@MainActor
struct Phase4IntegrationTests {
    let p2 = Phase2IntegrationTests()

    @Test func devicesConsentPushAndAccountDeletion() async throws {
        _ = try await p2.post("__e2e/reset")
        let email = "ios-acct-\(UUID().uuidString.prefix(6).lowercased())@example.com"
        let (auth, events) = try await p2.signedIn(email)

        let devices = try await auth.devices()
        #expect(devices.count == 1 && devices[0].current == true)
        try await auth.registerPushToken(Data(repeating: 0xAB, count: 32))

        _ = try await events.giveConsent(version: try await events.consent().version)
        #expect(try await events.consent().given)
        try await auth.withdrawConsent()
        #expect(try await events.consent().given == false)

        try await auth.sendDeletionCode()
        let (mail, _) = try await TestNet.session.data(from: Phase2IntegrationTests.api.appending(path: "__e2e/mail").appending(queryItems: [URLQueryItem(name: "to", value: email)]))
        let body = try #require((try JSONSerialization.jsonObject(with: mail) as? [String: String])?["body"])
        let code = try #require(body.firstMatch(of: /\b(\d{6})\b/)?.1)
        await #expect(throws: AppError.invalidCode) { try await auth.deleteAccount(code: code == "000000" ? "111111" : "000000") }
        try await auth.deleteAccount(code: String(code))
        #expect(await auth.session.hasSession == false)
        await #expect(throws: (any Error).self) { _ = try await auth.me() }  // the account is gone
    }
}
