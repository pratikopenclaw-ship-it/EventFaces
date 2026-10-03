import Foundation
import Testing
@testable import EventFaces

@MainActor
@Suite("App model")
struct AppModelTests {
    @Test func signingOutClearsTheSignedInBanner() async throws {
        let transport = FakeTransport()
        transport.handler = { _, _ in (204, "{}") }
        let session = SessionManager(store: InMemorySecretStore(), signerLoader: { _ in TestSigner() })
        let defaults = try #require(UserDefaults(suiteName: "app-model-tests-\(UUID().uuidString)"))
        let model = AppModel(auth: .make(session: session, config: testConfig, transport: transport), config: testConfig, defaults: defaults)
        let user = try JSONDecoder.api.decode(User.self, from: Data(userJSON().utf8))
        model.didSignIn(user)
        #expect(model.notice == .signedIn)
        await model.signOut()
        #expect(model.account == .signedOut)
        #expect(model.notice == nil)
    }

    @Test func openingASheetClearsTheNotice() async throws {
        let session = SessionManager(store: InMemorySecretStore(), signerLoader: { _ in TestSigner() })
        let defaults = try #require(UserDefaults(suiteName: "app-model-tests-\(UUID().uuidString)"))
        let model = AppModel(auth: .make(session: session, config: testConfig, transport: FakeTransport()), config: testConfig, defaults: defaults)
        let user = try JSONDecoder.api.decode(User.self, from: Data(userJSON().utf8))
        model.didSignIn(user)
        model.showJoin = true
        #expect(model.notice == nil)
        model.showJoin = false
        model.didSignIn(user)
        model.showSettings = true
        #expect(model.notice == nil)
    }
}

