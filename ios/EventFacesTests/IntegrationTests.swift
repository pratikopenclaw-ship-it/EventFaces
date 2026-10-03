import Foundation
import OpenAPIURLSession
import Testing
@testable import EventFaces

/// Against the real API (docker compose e2e stack on localhost:8000, test data only).
/// scripts/test.sh sets EF_INTEGRATION=1 (as TEST_RUNNER_EF_INTEGRATION) and starts the stack.
@Suite("Integration (local e2e API)", .serialized, .enabled(if: ProcessInfo.processInfo.environment["EF_INTEGRATION"] == "1"))
struct IntegrationTests {
    static let api = URL(string: "http://localhost:8000")!
    let config = AppConfig(apiBaseURL: api, appLinkHost: "localhost", appVersion: "1.0.0")

    func control(_ method: String, _ path: String, query: [URLQueryItem] = []) async throws -> Data {
        var request = URLRequest(url: Self.api.appending(path: path).appending(queryItems: query))
        request.httpMethod = method
        let (data, response) = try await TestNet.session.data(for: request)
        #expect((response as? HTTPURLResponse)?.statusCode == 200, "\(path)")
        return data
    }

    func lastMail(to email: String) async throws -> (subject: String, body: String) {
        let data = try await control("GET", "__e2e/mail", query: [URLQueryItem(name: "to", value: email)])
        let json = try #require(try JSONSerialization.jsonObject(with: data) as? [String: String])
        return (try #require(json["subject"]), try #require(json["body"]))
    }

    func signIn(_ email: String, store: SecretStore = InMemorySecretStore()) async throws -> (AuthService, SessionManager) {
        let session = SessionManager(store: store)
        let auth = AuthService.make(session: session, config: config, transport: URLSessionTransport(configuration: .init(session: NetworkSession.make())))
        await auth.install()
        try await auth.requestCode(email: email)
        let code = try await lastMail(to: email).subject.split(separator: " ").first.map(String.init)
        let user = try await auth.verify(email: email, code: try #require(code))
        #expect(user.email == email)
        return (auth, session)
    }

    @Test func codeSignInRefreshThemeAndLogout() async throws {
        _ = try await control("POST", "__e2e/reset")
        let email = "ios-\(UUID().uuidString.prefix(8).lowercased())@example.com"
        let store = InMemorySecretStore()
        let (auth, session) = try await signIn(email, store: store)
        #expect(try await auth.me().email == email)

        // A real device-signed refresh, verified by the server: the refresh token rotates.
        // (Access JWTs minted in the same second for the same session are identical, so
        // compare refresh tokens.)
        let refreshBefore = try store.data(for: "refresh-token")
        let before = try #require(try await session.validAccessToken())
        let after = try await session.refresh(replacing: before)
        #expect(try store.data(for: "refresh-token") != refreshBefore)
        #expect(try await auth.me().email == email)

        try await auth.setTheme(.dark)
        #expect(try await auth.me().theme == .dark)

        await auth.signOut()
        // The old access token died with the session.
        let stale = AuthService.make(
            session: SessionManager(store: InMemorySecretStore()), config: config,
            transport: URLSessionTransport(configuration: .init(session: NetworkSession.make()))
        )
        await #expect(throws: (any Error).self) {
            var request = URLRequest(url: Self.api.appending(path: "api/me"))
            request.setValue("Bearer \(after)", forHTTPHeaderField: "Authorization")
            request.setValue("1.0.0", forHTTPHeaderField: "X-App-Version")
            let (_, response) = try await TestNet.session.data(for: request)
            if (response as? HTTPURLResponse)?.statusCode == 401 { throw SessionEndedError() }
        }
        _ = stale
    }

    @Test func magicLinkFromTheEmailSignsIn() async throws {
        _ = try await control("POST", "__e2e/reset")
        let email = "ios-magic-\(UUID().uuidString.prefix(6).lowercased())@example.com"
        let session = SessionManager(store: InMemorySecretStore())
        let auth = AuthService.make(session: session, config: config, transport: URLSessionTransport(configuration: .init(session: NetworkSession.make())))
        try await auth.requestCode(email: email)
        let body = try await lastMail(to: email).body
        let link = try #require(body.split(whereSeparator: \.isWhitespace).first { $0.contains("/m/signin?t=") }.map(String.init))
        guard case let .signIn(token) = DeepLink.parse(URL(string: link)!, allowedHost: "localhost") else {
            Issue.record("the emailed link didn't parse: \(link)")
            return
        }
        #expect(try await auth.signIn(magicToken: token).email == email)
    }

    @Test func aRefreshSignedByAnotherKeyEndsTheSession() async throws {
        _ = try await control("POST", "__e2e/reset")
        let store = InMemorySecretStore()
        let (_, session) = try await signIn("ios-swap-\(UUID().uuidString.prefix(6).lowercased())@example.com", store: store)
        // Simulate a copied session on another phone: same refresh token, different key.
        try store.delete("device-key")
        let current = try await session.validAccessToken()
        await #expect(throws: SessionEndedError.self) { _ = try await session.refresh(replacing: current) }
        #expect(await session.hasSession == false)
    }

    @Test func outdatedAppsAreToldToUpdate() async throws {
        let session = SessionManager(store: InMemorySecretStore())
        let log = EventLog()
        await session.onEvent { log.add($0) }
        let old = AppConfig(apiBaseURL: Self.api, appLinkHost: "localhost", appVersion: "0.0.1")
        let auth = AuthService.make(session: session, config: old, transport: URLSessionTransport(configuration: .init(session: NetworkSession.make())))
        _ = try? await auth.requestCode(email: "old@example.com")
        try await Task.sleep(for: .milliseconds(100))
        #expect(log.events.count == 1)
        if case .updateRequired = log.events.first {} else { Issue.record("expected updateRequired") }
    }
}
