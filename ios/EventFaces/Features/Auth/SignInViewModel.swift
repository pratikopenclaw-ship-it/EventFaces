import Foundation
import Observation

@MainActor
@Observable
final class SignInViewModel {
    enum Step: Equatable { case email, code }

    var email = ""
    var code = "" {
        didSet {
            let digits = String(code.filter(\.isNumber).prefix(6))
            if digits != code { code = digits }
        }
    }
    /// "I accept the Terms of Use and am at least 16": required before a code is sent; the
    /// server records it when the code is verified.
    var acceptedTerms = false
    private(set) var step: Step = .email
    private(set) var busy = false
    private(set) var error: AppError?
    private(set) var resendAvailableAt: Date?

    private let auth: AuthService
    private let now: () -> Date
    static let resendDelay: TimeInterval = 30

    init(auth: AuthService, now: @escaping () -> Date = Date.init) {
        self.auth = auth
        self.now = now
    }

    var emailLooksValid: Bool {
        let trimmed = email.trimmingCharacters(in: .whitespaces)
        return trimmed.wholeMatch(of: /[^@\s]+@[^@\s]+\.[^@\s]+/) != nil && trimmed.count <= 254
    }

    var canResend: Bool { resendAvailableAt.map { now() >= $0 } ?? true }

    var canSendCode: Bool { emailLooksValid && acceptedTerms && !busy }

    func sendCode() async {
        guard emailLooksValid, acceptedTerms, !busy else { return }
        busy = true
        error = nil
        defer { busy = false }
        do {
            try await auth.requestCode(email: email.trimmingCharacters(in: .whitespaces))
            step = .code
            code = ""
            resendAvailableAt = now().addingTimeInterval(Self.resendDelay)
        } catch {
            self.error = Self.appError(error)
        }
    }

    /// Returns the user on success.
    func verify() async -> User? {
        guard code.count == 6, !busy else { return nil }
        busy = true
        error = nil
        defer { busy = false }
        do {
            return try await auth.verify(email: email.trimmingCharacters(in: .whitespaces), code: code, acceptedTerms: acceptedTerms)
        } catch {
            self.error = Self.appError(error)
            code = ""
            return nil
        }
    }

    func changeEmail() {
        step = .email
        code = ""
        error = nil
    }

    static func appError(_ error: Error) -> AppError {
        if let app = error as? AppError { return app }
        if (error as? URLError) != nil { return .offline }
        if let client = error as? ClientErrorWithUnderlying, client.underlying is URLError { return .offline }
        return .server(status: 0)
    }
}

/// Lets the view model see through OpenAPIRuntime's error wrapper without importing it here.
protocol ClientErrorWithUnderlying { var underlying: any Error { get } }
