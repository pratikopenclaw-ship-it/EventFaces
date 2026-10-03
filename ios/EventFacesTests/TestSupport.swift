import CryptoKit
import Foundation
import HTTPTypes
import OpenAPIRuntime
@testable import EventFaces

/// Scripted HTTP: records every request (headers + body) and answers from a handler.
final class FakeTransport: ClientTransport, @unchecked Sendable {
    struct Sent { let request: HTTPRequest; let body: Data? }
    private let lock = NSLock()
    private var _sent: [Sent] = []
    var handler: @Sendable (HTTPRequest, Data?) async throws -> (Int, String) = { _, _ in (200, "{}") }

    var sent: [Sent] { lock.withLock { _sent } }

    func send(_ request: HTTPRequest, body: HTTPBody?, baseURL: URL, operationID: String) async throws -> (HTTPResponse, HTTPBody?) {
        let data: Data? = if let body { try await Data(collecting: body, upTo: .max) } else { nil }
        lock.withLock { _sent.append(Sent(request: request, body: data)) }
        let (status, json) = try await handler(request, data)
        var response = HTTPResponse(status: .init(code: status))
        response.headerFields[.contentType] = "application/json"
        return (response, HTTPBody(json))
    }
}

/// Software device key for tests (the real one is in the Secure Enclave on devices).
struct TestSigner: DeviceSigner {
    let key = P256.Signing.PrivateKey()
    var publicKeyBase64: String { key.publicKey.x963Representation.base64EncodedString() }
    func signatureBase64(for message: Data) throws -> String { try key.signature(for: message).derRepresentation.base64EncodedString() }
}

let testConfig = AppConfig(apiBaseURL: URL(string: "https://api.test.example")!, appLinkHost: "eventfaces.example", appVersion: "1.2.3")

func userJSON(email: String = "me@example.com", theme: String = "system") -> String {
    #"{"id":"0b7c1e2a-1111-4c1e-9a0c-0305e82c3301","email":"\#(email)","role":"attendee","email_verified_at":"2026-10-01T09:30:12.528837Z","created_at":"2026-10-01T09:30:12.528837Z","theme":"\#(theme)"}"#
}

func tokensJSON(access: String = "access-1", refresh: String = "refresh-token-000000000001", device: String = "3f2504e0-4f89-11d3-9a0c-0305e82c3301") -> String {
    #"{"access_token":"\#(access)","refresh_token":"\#(refresh)","token_type":"bearer","expires_in":900,"device_id":"\#(device)","user":\#(userJSON())}"#
}

/// Repo root, for tests that check the app against shared files (tokens.json, plists).
let repoRoot = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()

/// Tests talk to the e2e server without a URL cache: `URLSession.shared` would cache the
/// test selfies on disk, which the container test must not mistake for the app's doing.
enum TestNet {
    static let session: URLSession = {
        let config = URLSessionConfiguration.ephemeral
        config.urlCache = nil
        return URLSession(configuration: config)
    }()
}
