import Foundation
import HTTPTypes
import Testing
@testable import EventFaces

/// Collects session events (they're delivered off the actor).
final class EventLog: @unchecked Sendable {
    private let lock = NSLock()
    private var _events: [SessionEvent] = []
    var events: [SessionEvent] { lock.withLock { _events } }
    func add(_ e: SessionEvent) { lock.withLock { _events.append(e) } }
}

@Suite("Session and API client")
struct SessionTests {
    let store = InMemorySecretStore()
    let transport = FakeTransport()

    func makeSession(signer: TestSigner = TestSigner()) -> SessionManager {
        SessionManager(store: store, signerLoader: { _ in signer }, clock: { Date(timeIntervalSince1970: 1_790_000_000) })
    }

    @Test func signInStoresOnlyTheRefreshTokenAndDeviceID() async throws {
        let session = makeSession()
        let auth = AuthService.make(session: session, config: testConfig, transport: transport)
        await auth.install()
        transport.handler = { req, _ in
            req.path == "/api/mobile/auth/code/verify" ? (200, tokensJSON()) : (404, "{}")
        }
        let user = try await auth.verify(email: "me@example.com", code: "123456", acceptedTerms: true)
        #expect(user.email == "me@example.com")
        #expect(try store.data(for: "refresh-token") == Data("refresh-token-000000000001".utf8))
        #expect(try store.data(for: "device-id") == Data("3f2504e0-4f89-11d3-9a0c-0305e82c3301".utf8))
        #expect(try store.data(for: "access-token") == nil)  // the access token stays in memory
        // Sign-in requests carry no bearer token and no cookies, but the app version.
        let sent = try #require(transport.sent.first)
        #expect(sent.request.headerFields[.authorization] == nil)
        #expect(sent.request.headerFields[.cookie] == nil)
        #expect(sent.request.headerFields[.appVersion] == "1.2.3")
    }

    @Test func authenticatedCallsCarryTheBearerToken() async throws {
        let session = makeSession()
        try await session.start(SessionTokens(accessToken: "access-1", refreshToken: "refresh-token-000000000001", deviceID: UUID()))
        let auth = AuthService.make(session: session, config: testConfig, transport: transport)
        transport.handler = { _, _ in (200, userJSON()) }
        _ = try await auth.me()
        #expect(transport.sent.last?.request.headerFields[.authorization] == "Bearer access-1")
    }

    @Test func a401RefreshesOnceWithASignatureAndRetries() async throws {
        let signer = TestSigner()
        let session = makeSession(signer: signer)
        let deviceID = UUID(uuidString: "3F2504E0-4F89-11D3-9A0C-0305E82C3301")!
        try await session.start(SessionTokens(accessToken: "stale", refreshToken: "refresh-token-000000000001", deviceID: deviceID))
        let auth = AuthService.make(session: session, config: testConfig, transport: transport)
        await auth.install()
        transport.handler = { req, body in
            switch req.path {
            case "/api/me":
                return req.headerFields[.authorization] == "Bearer access-2" ? (200, userJSON()) : (401, #"{"detail":"Not authenticated"}"#)
            case "/api/mobile/auth/refresh":
                let json = try JSONSerialization.jsonObject(with: body ?? Data()) as! [String: Any]
                // The signature covers this token, this device and this time.
                let message = DeviceKey.refreshMessage(refreshToken: json["refresh_token"] as! String, deviceID: deviceID, timestamp: json["ts"] as! Int)
                let sig = try P256Verify.signature(json["signature"] as! String)
                guard signer.key.publicKey.isValidSignature(sig, for: message), json["device_id"] as? String == "3f2504e0-4f89-11d3-9a0c-0305e82c3301" else {
                    return (401, "{}")
                }
                return (200, tokensJSON(access: "access-2", refresh: "refresh-token-000000000002"))
            default: return (404, "{}")
            }
        }
        _ = try await auth.me()
        #expect(transport.sent.map(\.request.path) == ["/api/me", "/api/mobile/auth/refresh", "/api/me"])
        #expect(try store.data(for: "refresh-token") == Data("refresh-token-000000000002".utf8))  // rotated
    }

    @Test func concurrent401sShareOneRefresh() async throws {
        let session = makeSession()
        try await session.start(SessionTokens(accessToken: "stale", refreshToken: "refresh-token-000000000001", deviceID: UUID()))
        let auth = AuthService.make(session: session, config: testConfig, transport: transport)
        await auth.install()
        transport.handler = { req, _ in
            if req.path == "/api/mobile/auth/refresh" {
                try await Task.sleep(for: .milliseconds(100))
                return (200, tokensJSON(access: "access-2"))
            }
            return req.headerFields[.authorization] == "Bearer access-2" ? (200, userJSON()) : (401, "{}")
        }
        try await withThrowingTaskGroup(of: Void.self) { group in
            for _ in 0..<8 { group.addTask { _ = try await auth.me() } }
            try await group.waitForAll()
        }
        // A rotated refresh token presented twice is treated as theft by the server.
        #expect(transport.sent.filter { $0.request.path == "/api/mobile/auth/refresh" }.count == 1)
    }

    @Test func aRefusedRefreshEndsTheSessionAndWipesSecrets() async throws {
        let session = makeSession()
        let log = EventLog()
        await session.onEvent { log.add($0) }
        try await session.start(SessionTokens(accessToken: "stale", refreshToken: "refresh-token-000000000001", deviceID: UUID()))
        try store.set(Data("handle".utf8), for: "device-key")
        let auth = AuthService.make(session: session, config: testConfig, transport: transport)
        await auth.install()
        transport.handler = { _, _ in (401, #"{"detail":"Session expired"}"#) }
        await #expect(throws: SessionEndedError.self) { _ = try await auth.me() }
        #expect(store.isEmpty)  // refresh token, device id and the device key are gone
        #expect(await session.hasSession == false)
        try await Task.sleep(for: .milliseconds(50))
        #expect(log.events == [.ended])
    }

    @Test func http426ReportsUpdateRequired() async throws {
        let session = makeSession()
        let log = EventLog()
        await session.onEvent { log.add($0) }
        let auth = AuthService.make(session: session, config: testConfig, transport: transport)
        transport.handler = { _, _ in (426, #"{"detail":"update_required","min_supported_version":"2.0.0","update_url":"https://apps.apple.com/app/id1"}"#) }
        _ = try? await auth.requestCode(email: "a@example.com")
        try await Task.sleep(for: .milliseconds(50))
        #expect(log.events == [.updateRequired(updateURL: URL(string: "https://apps.apple.com/app/id1"))])
    }

    @Test func a426WithANonHTTPSUpdateLinkIsIgnored() async throws {
        let session = makeSession()
        let log = EventLog()
        await session.onEvent { log.add($0) }
        let auth = AuthService.make(session: session, config: testConfig, transport: transport)
        transport.handler = { _, _ in (426, #"{"update_url":"javascript:alert(1)"}"#) }
        _ = try? await auth.requestCode(email: "a@example.com")
        try await Task.sleep(for: .milliseconds(50))
        #expect(log.events == [.updateRequired(updateURL: nil)])
    }

    @Test func signOutWipesLocallyEvenIfTheServerIsUnreachable() async throws {
        let session = makeSession()
        try await session.start(SessionTokens(accessToken: "a", refreshToken: "refresh-token-000000000001", deviceID: UUID()))
        let auth = AuthService.make(session: session, config: testConfig, transport: transport)
        transport.handler = { _, _ in throw URLError(.notConnectedToInternet) }
        await auth.signOut()
        #expect(store.isEmpty)
    }

    @Test func networkSessionSendsNoCookiesAndCachesNothing() {
        let config = NetworkSession.make().configuration
        #expect(config.httpCookieStorage == nil)
        #expect(config.httpShouldSetCookies == false)
        #expect(config.urlCache == nil)
        #expect(config.tlsMinimumSupportedProtocolVersion == .TLSv12)
    }

    @Test func apiDatesWithMicrosecondsDecode() throws {
        let date = try FlexibleISO8601().decode("2026-10-01T09:30:12.528837Z")
        #expect(abs(date.timeIntervalSince1970 - 1_790_847_012.528) < 0.01)
        _ = try FlexibleISO8601().decode("2026-10-01T09:30:12Z")
    }
}

import CryptoKit
enum P256Verify {
    static func signature(_ b64: String) throws -> P256.Signing.ECDSASignature {
        try P256.Signing.ECDSASignature(derRepresentation: Data(base64Encoded: b64) ?? Data())
    }
}
