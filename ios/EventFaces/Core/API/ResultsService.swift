import Foundation
import OpenAPIRuntime
import UIKit

typealias MyPhoto = Components.Schemas.MyPhotoOut
typealias ReportReason = Components.Schemas.ReportIn.ReasonPayload

/// Results, feedback, reports and downloads.
extension EventService {
    func photos(eventID: String) async throws -> [MyPhoto] {
        switch try await call2({ try await api.searchMyPhotos(path: .init(eventId: eventID)) }) {
        case let .ok(ok): return try ok.body.json
        case .unprocessableContent: throw AppError.server(status: 422)
        case let .undocumented(status, _): throw status == 403 ? AppError.noAccess : AuthService.error(status)
        }
    }

    /// Photos the organizers shared with everyone (venue, food: no faces, so no selfie
    /// needed), shaped like results so the grid and viewer can show them.
    func sharedPhotos(eventID: String) async throws -> [MyPhoto] {
        switch try await call2({ try await api.photosListSharedPhotos(path: .init(eventId: eventID), query: .init()) }) {
        case let .ok(ok): return try ok.body.json.map { MyPhoto(height: $0.height, id: $0.id, shortlisted: false, width: $0.width) }
        case .unprocessableContent: throw AppError.server(status: 422)
        case let .undocumented(status, _): throw status == 403 ? AppError.noAccess : AuthService.error(status)
        }
    }

    /// "This is me" / "Not me" (the server records it against the user's own match).
    func feedback(eventID: String, photoID: String, isMe: Bool) async throws {
        let body = Components.Schemas.FeedbackIn(photoId: photoID, verdict: isMe ? .me : .notMe)
        switch try await call2({ try await api.searchGiveFeedback(path: .init(eventId: eventID), body: .json(body)) }) {
        case let .undocumented(status, _): throw status == 403 ? AppError.noAccess : AuthService.error(status)
        case .unprocessableContent: throw AppError.server(status: 422)
        default: return  // 204 No Content
        }
    }

    /// "Photos of me are missing".
    func reportMissing(eventID: String) async throws {
        switch try await call2({ try await api.searchReportMissing(path: .init(eventId: eventID)) }) {
        case let .undocumented(status, _): throw status == 403 ? AppError.noAccess : AuthService.error(status)
        default: return  // 204 No Content
        }
    }

    /// Report a photo (including "it's me, please remove it").
    func report(eventID: String, photoID: String, reason: ReportReason, details: String) async throws {
        let body = Components.Schemas.ReportIn(details: details, reason: reason)
        switch try await call2({ try await api.moderationReportPhoto(path: .init(photoId: photoID, eventId: eventID), body: .json(body)) }) {
        case .created: return
        case .unprocessableContent: throw AppError.server(status: 422)
        case let .undocumented(status, _): throw status == 403 ? AppError.noAccess : AuthService.error(status)
        }
    }

    /// A short-lived download link for these photos (one: the JPEG; several: a ZIP).
    func downloadLink(eventID: String, photoIDs: [String]) async throws -> (path: String, count: Int) {
        switch try await call2({ try await api.searchCreateDownload(path: .init(eventId: eventID), body: .json(.init(photoIds: photoIDs))) }) {
        case let .ok(ok):
            let out = try ok.body.json
            return (out.url, out.count)
        case .unprocessableContent: throw AppError.server(status: 422)
        case let .undocumented(status, _): throw status == 403 ? AppError.noAccess : AuthService.error(status)
        }
    }

    /// A photo variant ("thumb" ~400 px, "preview" ~1600 px), from the protected cache or the API.
    func cachedImage(eventID: String, photoID: String, variant: String, maxPixel: CGFloat) async throws -> UIImage? {
        if let hit = await PhotoCache.shared.image(event: eventID, photo: photoID, variant: variant, maxPixel: maxPixel) { return hit }
        do {
            let data = try await image(path: "/api/events/\(eventID)/photos/\(photoID)/\(variant)")
            return try await PhotoCache.shared.store(data, event: eventID, photo: photoID, variant: variant, maxPixel: maxPixel)
        } catch AppError.noAccess {
            await PhotoCache.shared.purge(event: eventID)  // access ended or was revoked: forget its photos now
            throw AppError.noAccess
        }
    }

    /// Shortlists or un-shortlists one of this user's own matched/uploaded photos. Idempotent
    /// on the server, so a toggle that lands twice (e.g. a retry) is harmless.
    func shortlist(eventID: String, photoID: String, add: Bool) async throws {
        if add {
            switch try await call2({ try await api.searchAddToShortlist(path: .init(photoId: photoID, eventId: eventID)) }) {
            case let .undocumented(status, _): throw status == 403 ? AppError.noAccess : AuthService.error(status)
            default: return  // 204 No Content
            }
        } else {
            switch try await call2({ try await api.searchRemoveFromShortlist(path: .init(photoId: photoID, eventId: eventID)) }) {
            case let .undocumented(status, _): throw status == 403 ? AppError.noAccess : AuthService.error(status)
            default: return  // 204 No Content
            }
        }
    }

    private func call2<T>(_ op: () async throws -> T) async throws -> T {
        do { return try await op() } catch let error as ClientError { throw error.underlyingError }
    }
}
