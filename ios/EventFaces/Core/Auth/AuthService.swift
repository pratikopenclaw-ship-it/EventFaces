import Foundation
import OpenAPIRuntime
import UIKit

/// Why a call failed, in terms the UI can explain.
enum AppError: Error, Equatable {
    case invalidCode
    case linkExpired
    case tooManyAttempts
    case offline
    case sessionEnded
    case noAccess
    case consentRequired
    case server(status: Int)
}

typealias User = Components.Schemas.UserOut
typealias ThemePreference = Components.Schemas.ThemePreference

/// Passwordless sign-in and the account calls of Phase 1.
struct AuthService: Sendable {
    let session: SessionManager
    let api: Client
    /// Pre-login client (no bearer token).
    let publicAPI: Client
    /// App Attest (report-only); tests substitute a fake.
    var attestation: any AttestationProvider = SystemAttestation()

    static func make(session: SessionManager, config: AppConfig, transport: any ClientTransport) -> AuthService {
        AuthService(
            session: session,
            api: APIClientFactory.make(session: session, config: config, transport: transport),
            publicAPI: APIClientFactory.make(session: session, config: config, transport: transport, authenticate: false)
        )
    }

    static func live(session: SessionManager, config: AppConfig = .current) -> AuthService {
        let urlSession = NetworkSession.make()
        let service = AuthService(
            session: session,
            api: APIClientFactory.make(session: session, config: config, urlSession: urlSession),
            publicAPI: APIClientFactory.make(session: session, config: config, urlSession: urlSession, authenticate: false)
        )
        return service
    }

    /// Wire the session manager's refresh to the device-signed refresh endpoint.
    func install() async {
        let publicAPI = self.publicAPI
        await session.setAttestation(attestation)
        await session.setRefresher { refresh in
            let output = try await publicAPI.mobileRefresh(body: .json(.init(
                assertion: refresh.assertion,
                deviceId: refresh.deviceID.uuidString.lowercased(),
                refreshToken: refresh.refreshToken,
                signature: refresh.signature,
                ts: refresh.timestamp
            )))
            switch output {
            case let .ok(ok): return try Self.tokens(ok.body.json)
            case .unprocessableContent: throw SessionEndedError()
            case let .undocumented(status, _):
                if status == 401 { throw SessionEndedError() }
                throw AppError.server(status: status)
            }
        }
    }

    func requestCode(email: String) async throws {
        switch try await unwrapped({ try await publicAPI.mobileRequestCode(body: .json(.init(email: email))) }) {
        case .accepted: return
        case .unprocessableContent: throw AppError.invalidCode
        case let .undocumented(status, _): throw Self.error(status)
        }
    }

    func verify(email: String, code: String) async throws -> User {
        let output = try await unwrapped({ try await publicAPI.mobileVerifyCode(body: .json(.init(code: code, device: try await device(), email: email))) })
        switch output {
        case let .ok(ok): return try await start(ok.body.json)
        case .unprocessableContent: throw AppError.invalidCode
        case let .undocumented(status, _): throw status == 400 ? AppError.invalidCode : Self.error(status)
        }
    }

    func signIn(magicToken: String) async throws -> User {
        let output = try await unwrapped({ try await publicAPI.mobileMagicLink(body: .json(.init(device: try await device(), token: magicToken))) })
        switch output {
        case let .ok(ok): return try await start(ok.body.json)
        case .unprocessableContent: throw AppError.linkExpired
        case let .undocumented(status, _): throw status == 400 ? AppError.linkExpired : Self.error(status)
        }
    }

    func me() async throws -> User {
        switch try await unwrapped({ try await api.meMe() }) {
        case let .ok(ok): return try ok.body.json
        case let .undocumented(status, _): throw status == 401 ? AppError.sessionEnded : Self.error(status)
        }
    }

    func setTheme(_ theme: ThemePreference) async throws {
        switch try await unwrapped({ try await api.meUpdatePreferences(body: .json(.init(theme: theme))) }) {
        case .ok: return
        case .unprocessableContent: throw AppError.server(status: 422)
        case let .undocumented(status, _): throw Self.error(status)
        }
    }

    /// Sign out here: tell the server (best effort) and wipe local secrets regardless.
    func signOut() async {
        _ = try? await api.mobileLogout()
        await session.endLocally()
    }

    // MARK: -

    /// The generated client wraps transport and middleware errors in `ClientError`;
    /// callers want the cause (session ended, offline).
    private func unwrapped<T>(_ call: () async throws -> T) async throws -> T {
        do {
            return try await call()
        } catch let error as ClientError {
            throw error.underlyingError
        }
    }

    private func device() async throws -> Components.Schemas.DeviceIn {
        .init(name: await UIDevice.current.name, platform: .ios, publicKey: try await session.devicePublicKey())
    }

    private func start(_ body: Components.Schemas.MobileTokensOut) async throws -> User {
        try await session.start(Self.tokens(body))
        let service = self
        Task.detached { await service.attestDevice() }  // report-only, in the background
        return body.user
    }

    /// App Attest for this session (report-only; the server ignores it until enabled and
    /// the simulator has no App Attest).
    func attestDevice() async {
        let api = self.api
        await AppAttest.attestIfNeeded(
            provider: attestation,
            session: session,
            challenge: {
                switch try await api.mobileAttestChallenge() {
                case let .ok(ok): return Data(base64Encoded: try ok.body.json.challenge)
                default: return nil  // 404: off on this server
                }
            },
            submit: { keyID, attestation in
                let output = try await api.mobileAttest(body: .json(.init(attestation: attestation.base64EncodedString(), keyId: keyID)))
                guard case let .ok(ok) = output else { return false }
                return try ok.body.json.status == .verified
            }
        )
    }

    static func tokens(_ body: Components.Schemas.MobileTokensOut) throws -> SessionTokens {
        guard let id = UUID(uuidString: body.deviceId) else { throw AppError.server(status: 200) }
        return SessionTokens(accessToken: body.accessToken, refreshToken: body.refreshToken, deviceID: id)
    }

    static func error(_ status: Int) -> AppError {
        switch status {
        case 429: .tooManyAttempts
        case 401: .sessionEnded
        default: .server(status: status)
        }
    }
}
