import Foundation
import OpenAPIURLSession
import Testing
@testable import EventFaces

/// Terms acceptance in the app: asked at sign-in, asked again when the Terms change, and
/// the Organizer Terms before managing events.
@Suite("Legal documents and acceptance")
@MainActor
struct LegalTests {
    let transport = FakeTransport()

    func makeModel() throws -> AppModel {
        let session = SessionManager(store: InMemorySecretStore(), signerLoader: { _ in TestSigner() })
        let defaults = try #require(UserDefaults(suiteName: "legal-tests-\(UUID().uuidString)"))
        return AppModel(auth: .make(session: session, config: testConfig, transport: transport), config: testConfig, defaults: defaults)
    }

    @Test(arguments: [("accept-terms", LegalDocumentKind.terms), ("accept-organizer-terms", .organizerTerms)])
    func aRequiredActionAsksForAcceptance(header: String, expected: LegalDocumentKind) async throws {
        let model = try makeModel()
        await model.start()
        try await model.auth.session.start(SessionTokens(accessToken: "a", refreshToken: "refresh-token-000000000001", deviceID: UUID()))
        transport.responseHeaders = ["X-Required-Action": header]
        transport.handler = { _, _ in (403, #"{"detail":"Please accept"}"#) }
        _ = try? await model.events.events()
        try await Task.sleep(for: .milliseconds(100))  // session events arrive on the main actor
        #expect(model.requiredAcceptance == expected)
    }

    @Test func aPlain403AsksForNothing() async throws {
        let model = try makeModel()
        await model.start()
        try await model.auth.session.start(SessionTokens(accessToken: "a", refreshToken: "refresh-token-000000000001", deviceID: UUID()))
        transport.handler = { _, _ in (403, #"{"detail":"No access"}"#) }
        _ = try? await model.events.events()
        try await Task.sleep(for: .milliseconds(100))
        #expect(model.requiredAcceptance == nil)
    }

    @Test func outdatedTermsAreAskedForAfterSignIn() throws {
        let model = try makeModel()
        model.didSignIn(try JSONDecoder.api.decode(User.self, from: Data(userJSON(termsAccepted: false).utf8)))
        #expect(model.requiredAcceptance == .terms)
        model.didAccept(try JSONDecoder.api.decode(User.self, from: Data(userJSON().utf8)))
        #expect(model.requiredAcceptance == nil)
    }

    @Test func aSignInLinkAsksForTheTermsUnlessTheyWereJustTicked() async throws {
        let model = try makeModel()
        await model.start()
        transport.handler = { req, _ in req.path == "/api/mobile/auth/magic" ? (200, tokensJSON()) : (200, "[]") }
        await model.follow(.signIn(token: "magic-token-0000000000001"))
        #expect(model.pendingMagicToken == "magic-token-0000000000001" && model.showSignIn)
        #expect(!transport.sent.contains { $0.request.path == "/api/mobile/auth/magic" })  // nothing sent yet
        await model.completeMagicSignIn()
        let sent = try #require(transport.sent.first { $0.request.path == "/api/mobile/auth/magic" })
        let json = try JSONSerialization.jsonObject(with: sent.body ?? Data()) as! [String: Any]
        #expect(json["accept_terms"] as? Bool == true)
        #expect(model.pendingMagicToken == nil)
    }

    @Test func aChangedVersionIsReportedSoTheTextIsShownAgain() async throws {
        let model = try makeModel()
        try await model.auth.session.start(SessionTokens(accessToken: "a", refreshToken: "refresh-token-000000000001", deviceID: UUID()))
        transport.handler = { _, _ in (409, #"{"detail":"These terms have changed."}"#) }
        await #expect(throws: AppError.legalChanged) { _ = try await model.auth.acceptLegal(.terms, version: "2020-01-01") }
    }

    @Test func signingOutForgetsPendingAcceptance() async throws {
        let model = try makeModel()
        model.requiredAcceptance = .terms
        model.termsTickedForSignIn = true
        await model.signOut()
        #expect(model.requiredAcceptance == nil && !model.termsTickedForSignIn)
    }
}

/// Against the real e2e API (test data only).
@Suite("Legal (local e2e API)", .serialized, .enabled(if: ProcessInfo.processInfo.environment["EF_INTEGRATION"] == "1"))
@MainActor
struct LegalIntegrationTests {
    let phase2 = Phase2IntegrationTests()

    @Test func documentsArePublicVersionedAndInBothLanguages() async throws {
        let session = SessionManager(store: InMemorySecretStore())
        let auth = AuthService.make(session: session, config: phase2.config, transport: URLSessionTransport(configuration: .init(session: NetworkSession.make())))
        for kind in LegalDocumentKind.allCases {
            let german = try await auth.legalDocument(kind, language: "de")
            let english = try await auth.legalDocument(kind, language: "en")
            #expect(german.locale.rawValue == "de" && english.locale.rawValue == "en")
            #expect(german.version == english.version && !german.sections.isEmpty)
            #expect(german.sections.count == english.sections.count)
        }
    }

    @Test func outdatedTermsBlockEventsUntilAccepted() async throws {
        _ = try await phase2.post("__e2e/reset")
        let email = "ios-legal-\(UUID().uuidString.prefix(6).lowercased())@example.com"
        let (auth, events) = try await phase2.signedIn(email)
        #expect(try await auth.me().termsAccepted)  // accepted at sign-in
        _ = try await phase2.post("__e2e/legal/reset", query: [URLQueryItem(name: "email", value: email)])
        #expect(try await !auth.me().termsAccepted)
        await #expect(throws: (any Error).self) { _ = try await events.events() }  // 403 + X-Required-Action
        let current = try await auth.legalDocument(.terms)
        let user = try await auth.acceptLegal(.terms, version: current.version)
        #expect(user.termsAccepted)
        _ = try await events.events()
    }
}
