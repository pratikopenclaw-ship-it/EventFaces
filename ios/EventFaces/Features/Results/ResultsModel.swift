import Foundation
import Observation
import UIKit

@MainActor
@Observable
final class ResultsModel {
    enum Section: String, CaseIterable, Identifiable { case best, possible, uploads; var id: String { rawValue } }
    /// `mine`: your matches and uploads. `shared`: photos the organizers shared with
    /// everyone (no faces, so no verdicts, shortlist or "missing" report).
    enum Source { case mine, shared }

    let eventID: String
    let source: Source
    private let service: EventService
    private let session: SessionManager
    private let config: AppConfig
    private(set) var photos: [MyPhoto] = []
    private(set) var loading = true
    private(set) var noAccess = false
    private(set) var message: Message?
    private(set) var busy = false
    var selecting = false
    var selected: Set<String> = []
    var shortlistedOnly = false
    /// A file ready to share (ZIP or JPEG); the view presents the share sheet.
    var shareFile: URL?

    enum Message: Equatable { case missingReported, saved, downloadFailed, saveFailed, expired, tooManyReports, failed }

    init(eventID: String, source: Source = .mine, service: EventService, session: SessionManager, config: AppConfig) {
        self.eventID = eventID
        self.source = source
        self.service = service
        self.session = session
        self.config = config
    }

    func photos(in section: Section) -> [MyPhoto] {
        photos.filter {
            guard !shortlistedOnly || $0.shortlisted else { return false }
            switch section {
            case .best: return $0.tier == .best
            case .possible: return $0.tier == .possible
            case .uploads: return $0.tier == nil
            }
        }
    }

    /// Viewer order: best, then possible, then own uploads.
    var ordered: [MyPhoto] { Section.allCases.flatMap { photos(in: $0) } }

    /// Matches only (own uploads aren't "found you" results), for the results headline.
    var matchCount: Int { photos.filter { $0.tier != nil }.count }

    func load() async {
        loading = true
        defer { loading = false }
        do {
            switch source {
            case .mine:
                photos = try await service.photos(eventID: eventID)
                // Drops cached photos you lost access to. Not for the shared list: it would
                // evict your own matches (the next "My photos" load evicts unshared ones).
                await PhotoCache.shared.keepOnly(event: eventID, photos: Set(photos.map(\.id)))
            case .shared:
                photos = try await service.sharedPhotos(eventID: eventID)
            }
        } catch AppError.noAccess {
            noAccess = true
            photos = []
            await PhotoCache.shared.purge(event: eventID)
        } catch {
            message = .failed
        }
    }

    func verdict(_ photo: MyPhoto, isMe: Bool) async {
        do {
            try await service.feedback(eventID: eventID, photoID: photo.id, isMe: isMe)
            if isMe {
                if let i = photos.firstIndex(where: { $0.id == photo.id }) { photos[i].verdict = .me }
            } else {
                photos.removeAll { $0.id == photo.id }  // a rejected match leaves the list (as on the web)
                selected.remove(photo.id)
                await PhotoCache.shared.keepOnly(event: eventID, photos: Set(photos.map(\.id)))
            }
        } catch AppError.noAccess {
            await lostAccess()
        } catch {
            message = .failed
        }
    }

    func toggleShortlist(_ photo: MyPhoto) async {
        let add = !photo.shortlisted
        guard let i = photos.firstIndex(where: { $0.id == photo.id }) else { return }
        photos[i].shortlisted = add  // optimistic; the toggle is idempotent server-side
        do {
            try await service.shortlist(eventID: eventID, photoID: photo.id, add: add)
        } catch AppError.noAccess {
            await lostAccess()
        } catch {
            if let i = photos.firstIndex(where: { $0.id == photo.id }) { photos[i].shortlisted = !add }
            message = .failed
        }
    }

    func reportMissing() async {
        do {
            try await service.reportMissing(eventID: eventID)
            message = .missingReported
        } catch AppError.tooManyAttempts {
            message = .tooManyReports
        } catch {
            message = .failed
        }
    }

    /// Originals through a short-lived download link: one photo → JPEG, several → ZIP.
    func download(_ ids: [String]) async -> URL? {
        guard !ids.isEmpty, !busy else { return nil }
        busy = true
        defer { busy = false }
        do {
            let link = try await service.downloadLink(eventID: eventID, photoIDs: ids)
            guard let token = try await session.validAccessToken() else { throw AppError.sessionEnded }
            let name = ids.count == 1 ? "photo-\(ids[0].prefix(8))" : "eventfaces-photos"
            return try await DownloadManager.shared.download(path: link.path, config: config, accessToken: token, suggestedName: name)
        } catch AppError.noAccess {
            await lostAccess()
        } catch DownloadManager.Failure.expired {
            message = .expired
        } catch {
            message = .downloadFailed
        }
        return nil
    }

    func shareSelection() async {
        if let file = await download(Array(selected)) { shareFile = file }
    }

    func downloadAll() async {
        if let file = await download(ordered.map(\.id)) { shareFile = file }
    }

    func save(_ ids: [String]) async {
        for id in ids {
            guard let file = await download([id]) else { return }
            do {
                try await DownloadManager.saveToPhotos(file)
                try? FileManager.default.removeItem(at: file)
            } catch {
                message = .saveFailed
                return
            }
        }
        message = .saved
        selecting = false
        selected = []
    }

    func toggle(_ id: String) {
        if selected.contains(id) { selected.remove(id) } else { selected.insert(id) }
    }

    func dismissMessage() { message = nil }

    private func lostAccess() async {
        noAccess = true
        photos = []
        await PhotoCache.shared.purge(event: eventID)
    }
}
