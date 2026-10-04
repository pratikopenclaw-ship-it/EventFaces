import Foundation
import Testing
@testable import EventFaces

@MainActor
@Suite("Sign-in view model")
struct SignInViewModelTests {
    let transport = FakeTransport()
    var auth: AuthService { AuthService.make(session: SessionManager(store: InMemorySecretStore(), signerLoader: { _ in TestSigner() }), config: testConfig, transport: transport) }

    @Test func codeFieldKeepsSixDigitsOnly() {
        let vm = SignInViewModel(auth: auth)
        vm.code = "12a3-4 5678"
        #expect(vm.code == "123456")
    }

    @Test(arguments: [("me@example.com", true), ("me@example", false), ("no-at.example.com", false), ("a b@example.com", false), ("", false)])
    func emailValidation(email: String, valid: Bool) {
        let vm = SignInViewModel(auth: auth)
        vm.email = email
        #expect(vm.emailLooksValid == valid)
    }

    @Test func sendingMovesToTheCodeStepAndThrottlesResend() async {
        var clock = Date(timeIntervalSince1970: 1000)
        let vm = SignInViewModel(auth: auth, now: { clock })
        transport.handler = { _, _ in (202, #"{"detail":"ok"}"#) }
        vm.email = "me@example.com"
        vm.acceptedTerms = true
        await vm.sendCode()
        #expect(vm.step == .code && vm.error == nil)
        #expect(!vm.canResend)
        clock = clock.addingTimeInterval(SignInViewModel.resendDelay)
        #expect(vm.canResend)
    }

    @Test func noCodeIsSentUntilTheTermsAreAccepted() async throws {
        let vm = SignInViewModel(auth: auth)
        transport.handler = { _, _ in (202, #"{"detail":"ok"}"#) }
        vm.email = "me@example.com"
        #expect(!vm.canSendCode)
        await vm.sendCode()
        #expect(vm.step == .email && transport.sent.isEmpty)
        vm.acceptedTerms = true
        #expect(vm.canSendCode)
        await vm.sendCode()
        #expect(vm.step == .code)
    }

    @Test func verifyingSendsTheAcceptance() async throws {
        let vm = SignInViewModel(auth: auth)
        transport.handler = { req, _ in req.path == "/api/mobile/auth/code/verify" ? (200, tokensJSON()) : (202, #"{"detail":"ok"}"#) }
        vm.email = "me@example.com"
        vm.acceptedTerms = true
        await vm.sendCode()
        vm.code = "123456"
        #expect(await vm.verify() != nil)
        let sent = try #require(transport.sent.last { $0.request.path == "/api/mobile/auth/code/verify" })
        let json = try JSONSerialization.jsonObject(with: sent.body ?? Data()) as! [String: Any]
        #expect(json["accept_terms"] as? Bool == true)
    }

    @Test(arguments: [(400, AppError.invalidCode), (429, AppError.tooManyAttempts), (500, AppError.server(status: 500))])
    func verifyErrorsAreExplained(status: Int, expected: AppError) async {
        let vm = SignInViewModel(auth: auth)
        transport.handler = { _, _ in (status, #"{"detail":"x"}"#) }
        vm.email = "me@example.com"
        vm.code = "123456"
        #expect(await vm.verify() == nil)
        #expect(vm.error == expected)
        #expect(vm.code.isEmpty)  // cleared for the next try
    }

    @Test func offlineIsReportedAsOffline() async {
        let vm = SignInViewModel(auth: auth)
        transport.handler = { _, _ in throw URLError(.notConnectedToInternet) }
        vm.email = "me@example.com"
        vm.acceptedTerms = true
        await vm.sendCode()
        #expect(vm.error == .offline)
    }
}
