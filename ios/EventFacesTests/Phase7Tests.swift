import CryptoKit
import Foundation
import Testing
@testable import EventFaces

/// Stands in for DCAppAttestService (the simulator has none).
final class FakeAttestation: AttestationProvider, @unchecked Sendable {
    let lock = NSLock()
    var isSupported = true
    var failAssertions = false
    private(set) var attestedHashes: [Data] = []
    private(set) var assertedHashes: [Data] = []

    func generateKey() async throws -> String { Data(repeating: 7, count: 32).base64EncodedString() }

    func attestKey(_ keyID: String, clientDataHash: Data) async throws -> Data {
        lock.withLock { attestedHashes.append(clientDataHash) }
        return Data("attestation".utf8)
    }

    func generateAssertion(_ keyID: String, clientDataHash: Data) async throws -> Data {
        if failAssertions { throw CocoaError(.featureUnsupported) }
        lock.withLock { assertedHashes.append(clientDataHash) }
        return Data("assertion".utf8)
    }
}

@Suite("App Attest (report-only)")
struct AppAttestTests {
    let store = InMemorySecretStore()
    let transport = FakeTransport()
    let fake = FakeAttestation()
    let challenge = Data(repeating: 42, count: 32)

    func makeAuth() async throws -> AuthService {
        let session = SessionManager(store: store, signerLoader: { _ in TestSigner() }, clock: { Date(timeIntervalSince1970: 1_790_000_000) })
        try await session.start(SessionTokens(accessToken: "access-1", refreshToken: "refresh-token-000000000001", deviceID: UUID()))
        var auth = AuthService.make(session: session, config: testConfig, transport: transport)
        auth.attestation = fake
        await auth.install()
        return auth
    }

    func serve(status: String = "verified", challengeStatus: Int = 200) {
        let challenge = self.challenge.base64EncodedString()
        transport.handler = { req, body in
            switch req.path {
            case "/api/me/devices/current/attest/challenge":
                return (challengeStatus, challengeStatus == 200 ? #"{"challenge":"\#(challenge)"}"# : #"{"detail":"off"}"#)
            case "/api/me/devices/current/attest":
                let json = try JSONSerialization.jsonObject(with: body ?? Data()) as! [String: Any]
                #expect(json["key_id"] as? String == Data(repeating: 7, count: 32).base64EncodedString())
                #expect(json["attestation"] as? String == Data("attestation".utf8).base64EncodedString())
                return (200, #"{"status":"\#(status)"}"#)
            case "/api/mobile/auth/refresh":
                return (200, tokensJSON(access: "access-2", refresh: "refresh-token-000000000002"))
            default:
                return (404, "{}")
            }
        }
    }

    @Test func attestsOverTheServerChallengeAndKeepsAVerifiedKey() async throws {
        let auth = try await makeAuth()
        serve()
        await auth.attestDevice()
        #expect(fake.attestedHashes == [Data(SHA256.hash(data: challenge))])
        #expect(await auth.session.attestKeyID() == Data(repeating: 7, count: 32).base64EncodedString())
        await auth.attestDevice()  // once per session
        #expect(fake.attestedHashes.count == 1)
    }

    @Test func aFailedAttestationKeepsNoKey() async throws {
        let auth = try await makeAuth()
        serve(status: "failed")
        await auth.attestDevice()
        #expect(await auth.session.attestKeyID() == nil)
    }

    @Test func nothingHappensWhenTheServerHasItOffOrTheDeviceCant() async throws {
        let auth = try await makeAuth()
        serve(challengeStatus: 404)
        await auth.attestDevice()
        #expect(fake.attestedHashes.isEmpty)
        fake.isSupported = false
        serve()
        await auth.attestDevice()
        #expect(fake.attestedHashes.isEmpty)
        #expect(!transport.sent.contains { $0.request.path == "/api/me/devices/current/attest" })
    }

    @Test func refreshesCarryAnAssertionOverTheSignedMessage() async throws {
        let auth = try await makeAuth()
        serve()
        await auth.attestDevice()
        _ = try await auth.session.refresh(replacing: "access-1")
        let sent = try #require(transport.sent.last { $0.request.path == "/api/mobile/auth/refresh" })
        let json = try JSONSerialization.jsonObject(with: sent.body ?? Data()) as! [String: Any]
        #expect(json["assertion"] as? String == Data("assertion".utf8).base64EncodedString())
        let message = DeviceKey.refreshMessage(
            refreshToken: "refresh-token-000000000001", deviceID: try #require(UUID(uuidString: json["device_id"] as! String)), timestamp: json["ts"] as! Int
        )
        #expect(fake.assertedHashes == [Data(SHA256.hash(data: message))])
    }

    @Test func refreshWorksWithoutAnAssertion() async throws {
        let auth = try await makeAuth()
        serve()
        _ = try await auth.session.refresh(replacing: "access-1")  // not attested: no assertion
        await auth.attestDevice()
        fake.failAssertions = true
        _ = try await auth.session.refresh(replacing: "access-2")  // assertion failed: still refreshes
        let bodies = try transport.sent.filter { $0.request.path == "/api/mobile/auth/refresh" }
            .map { try JSONSerialization.jsonObject(with: $0.body ?? Data()) as! [String: Any] }
        #expect(bodies.count == 2)
        #expect(bodies.allSatisfy { $0["assertion"] == nil || $0["assertion"] is NSNull })
    }

    @Test func signingOutForgetsTheAttestedKey() async throws {
        let auth = try await makeAuth()
        serve()
        await auth.attestDevice()
        await auth.session.endLocally()
        #expect(await auth.session.attestKeyID() == nil)
        #expect(store.isEmpty)
    }
}
