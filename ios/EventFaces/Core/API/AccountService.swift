import Foundation
import OpenAPIRuntime

typealias DeviceInfo = Components.Schemas.DeviceOut

/// Account and privacy calls (Phase 4).
extension AuthService {
    func devices() async throws -> [DeviceInfo] {
        switch try await wrapped({ try await api.mobileListDevices() }) {
        case let .ok(ok): return try ok.body.json
        case let .undocumented(status, _): throw AuthService.error(status)
        }
    }

    func revokeDevice(_ id: String) async throws {
        switch try await wrapped({ try await api.mobileRevokeDevice(path: .init(deviceId: id)) }) {
        case .undocumented(404, _): return  // already gone
        case let .undocumented(status, _): throw AuthService.error(status)
        default: return
        }
    }

    /// "Delete my data": withdraw face-search consent. The server deletes the photos you
    /// matched and unlinks your feedback; the account stays.
    func withdrawConsent() async throws {
        switch try await wrapped({ try await api.searchWithdrawConsent() }) {
        case .ok: return
        case let .undocumented(status, _): throw AuthService.error(status)
        }
    }

    /// Accounts made by code sign-in have no password: deleting one is confirmed with an
    /// emailed code.
    func sendDeletionCode() async throws {
        switch try await wrapped({ try await api.privacySendReauthCode() }) {
        case let .undocumented(status, _): throw AuthService.error(status)
        default: return
        }
    }

    func deleteAccount(code: String) async throws {
        switch try await wrapped({ try await api.privacyDeleteMe(body: .json(.init(code: code))) }) {
        case .ok: break
        case .unprocessableContent: throw AppError.invalidCode
        case let .undocumented(status, _): throw status == 403 ? AppError.invalidCode : AuthService.error(status)
        }
        await session.endLocally()
    }

    func registerPushToken(_ token: Data) async throws {
        let body = Components.Schemas.PushTokenIn(env: PushToken.environment == "sandbox" ? .sandbox : .production, token: PushToken.hex(token))
        switch try await wrapped({ try await api.mobileRegisterPush(body: .json(body)) }) {
        case let .undocumented(status, _): throw AuthService.error(status)
        case .unprocessableContent: throw AppError.server(status: 422)
        default: return
        }
    }

    private func wrapped<T>(_ op: () async throws -> T) async throws -> T {
        do { return try await op() } catch let error as ClientError { throw error.underlyingError }
    }
}
