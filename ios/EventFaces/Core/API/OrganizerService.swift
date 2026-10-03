import Foundation
import OpenAPIRuntime

typealias EventAdmin = Components.Schemas.EventAdminOut
typealias SyncStatusInfo = Components.Schemas.SyncStatusOut
typealias ModerationItem = Components.Schemas.ModerationItem
typealias Member = Components.Schemas.MemberOut

/// Organizer lite (Phase 6): read-mostly event management. No Drive linking or event
/// creation in the app; those stay on the web.
extension EventService {
    func admin(_ id: String) async throws -> EventAdmin {
        switch try await call4({ try await api.eventsGetEventAdmin(path: .init(eventId: id)) }) {
        case let .ok(ok): return try ok.body.json
        case .unprocessableContent: throw AppError.server(status: 422)
        case let .undocumented(status, _): throw status == 403 ? AppError.noAccess : AuthService.error(status)
        }
    }

    func syncStatus(_ id: String) async throws -> SyncStatusInfo {
        switch try await call4({ try await api.photosSyncStatus(path: .init(eventId: id)) }) {
        case let .ok(ok): return try ok.body.json
        case .unprocessableContent: throw AppError.server(status: 422)
        case let .undocumented(status, _): throw status == 403 ? AppError.noAccess : AuthService.error(status)
        }
    }

    func moderationQueue(_ id: String) async throws -> [ModerationItem] {
        switch try await call4({ try await api.moderationModerationQueue(path: .init(eventId: id)) }) {
        case let .ok(ok): return try ok.body.json
        case .unprocessableContent: throw AppError.server(status: 422)
        case let .undocumented(status, _): throw status == 403 ? AppError.noAccess : AuthService.error(status)
        }
    }

    func moderate(_ eventID: String, photoID: String, approve: Bool) async throws {
        switch try await call4({ try await api.moderationModerate(path: .init(photoId: photoID, eventId: eventID), body: .json(.init(action: approve ? .approve : .reject))) }) {
        case let .undocumented(status, _): throw status == 403 ? AppError.noAccess : AuthService.error(status)
        case .unprocessableContent: throw AppError.server(status: 422)
        default: return
        }
    }

    func deletePhoto(_ eventID: String, photoID: String) async throws {
        switch try await call4({ try await api.moderationDeletePhoto(path: .init(photoId: photoID, eventId: eventID)) }) {
        case let .undocumented(status, _): throw status == 403 ? AppError.noAccess : AuthService.error(status)
        case .unprocessableContent: throw AppError.server(status: 422)
        default: return
        }
    }

    func members(_ id: String) async throws -> [Member] {
        switch try await call4({ try await api.membersListMembers(path: .init(eventId: id)) }) {
        case let .ok(ok): return try ok.body.json
        case .unprocessableContent: throw AppError.server(status: 422)
        case let .undocumented(status, _): throw status == 403 ? AppError.noAccess : AuthService.error(status)
        }
    }

    func revoke(_ eventID: String, userID: String) async throws {
        switch try await call4({ try await api.membersUpdateMember(path: .init(userId: userID, eventId: eventID), body: .json(.init(status: .revoked))) }) {
        case .ok: return
        case .unprocessableContent: throw AppError.server(status: 422)
        case let .undocumented(status, _): throw status == 403 ? AppError.noAccess : AuthService.error(status)
        }
    }

    private func call4<T>(_ op: () async throws -> T) async throws -> T {
        do { return try await op() } catch let error as ClientError { throw error.underlyingError }
    }
}
