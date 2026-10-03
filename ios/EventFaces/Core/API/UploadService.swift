import Foundation
import OpenAPIRuntime

typealias MyUpload = Components.Schemas.MyUploadOut

extension EventService {
    struct UploadTicket: Sendable { let photoID: String; let url: URL; let contentType: String }

    func startUpload(eventID: String, filename: String, contentType: String, size: Int) async throws -> UploadTicket {
        let body = Components.Schemas.UploadStartIn(contentType: contentType, filename: filename, size: size)
        switch try await call3({ try await api.uploadsStartUpload(path: .init(eventId: eventID), body: .json(body)) }) {
        case let .created(created):
            let out = try created.body.json
            guard let url = URL(string: out.uploadUrl) else { throw AppError.server(status: 0) }
            return UploadTicket(photoID: out.photoId, url: url, contentType: out.contentType)
        case .unprocessableContent: throw AppError.server(status: 422)
        case let .undocumented(status, _): throw UploadError.from(status)
        }
    }

    func completeUpload(eventID: String, photoID: String) async throws -> MyUpload {
        switch try await call3({ try await api.uploadsCompleteUpload(path: .init(photoId: photoID, eventId: eventID)) }) {
        case let .ok(ok): return try ok.body.json
        case .unprocessableContent: throw AppError.server(status: 422)
        case let .undocumented(status, _): throw UploadError.from(status)
        }
    }

    func myUploads(eventID: String) async throws -> [MyUpload] {
        switch try await call3({ try await api.uploadsMyUploads(path: .init(eventId: eventID)) }) {
        case let .ok(ok): return try ok.body.json
        case .unprocessableContent: throw AppError.server(status: 422)
        case let .undocumented(status, _): throw status == 403 ? AppError.noAccess : AuthService.error(status)
        }
    }

    private func call3<T>(_ op: () async throws -> T) async throws -> T {
        do { return try await op() } catch let error as ClientError { throw error.underlyingError }
    }
}

enum UploadError: Error, Equatable {
    case tooLarge, unsupportedType, quotaReached, notAllowed, notArrived, rateLimited, server

    static func from(_ status: Int) -> Error {
        switch status {
        case 413: UploadError.tooLarge
        case 415: UploadError.unsupportedType
        case 409: UploadError.notArrived
        case 429: UploadError.rateLimited
        case 403: UploadError.notAllowed
        case 400: UploadError.quotaReached
        default: AuthService.error(status)
        }
    }
}
