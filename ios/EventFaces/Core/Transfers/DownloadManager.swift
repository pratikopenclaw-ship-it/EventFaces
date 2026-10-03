import Foundation
import Photos
import UIKit

/// Downloads of originals and ZIPs through the API's short-lived download links. Large
/// downloads run on a background URLSession, so they finish if the app is suspended; the
/// file lands in a protected temporary folder and is handed to Save / the share sheet.
final class DownloadManager: NSObject, @unchecked Sendable {
    static let shared = DownloadManager()
    static let sessionID = "app.eventfaces.downloads"

    enum Failure: Error, Equatable { case expired, noAccess, network, server }

    private var continuations: [Int: CheckedContinuation<URL, Error>] = [:]
    private let lock = NSLock()
    var backgroundCompletion: (() -> Void)?

    private lazy var session: URLSession = {
        let config = URLSessionConfiguration.background(withIdentifier: Self.sessionID)
        config.httpCookieStorage = nil
        config.httpShouldSetCookies = false
        config.urlCache = nil
        config.sessionSendsLaunchEvents = true
        config.isDiscretionary = false
        return URLSession(configuration: config, delegate: self, delegateQueue: nil)
    }()

    static var folder: URL {
        FileManager.default.temporaryDirectory.appending(path: "EventFacesDownloads", directoryHint: .isDirectory)
    }

    /// Download the file behind a download link (relative to the API) with the bearer token.
    func download(path: String, config: AppConfig, accessToken: String, suggestedName: String) async throws -> URL {
        var request = URLRequest(url: URL(string: path, relativeTo: config.apiBaseURL)!)
        request.setValue("Bearer \(accessToken)", forHTTPHeaderField: "Authorization")
        request.setValue(config.appVersion, forHTTPHeaderField: "X-App-Version")
        let temp: URL = try await withCheckedThrowingContinuation { continuation in
            let task = session.downloadTask(with: request)
            task.taskDescription = suggestedName
            lock.withLock { continuations[task.taskIdentifier] = continuation }
            task.resume()
        }
        return temp
    }

    /// Save a downloaded JPEG with add-only permission, asked only now (when saving).
    static func saveToPhotos(_ file: URL) async throws {
        let status = await PHPhotoLibrary.requestAuthorization(for: .addOnly)
        guard status == .authorized || status == .limited else { throw Failure.noAccess }
        try await PHPhotoLibrary.shared().performChanges {
            PHAssetCreationRequest.forAsset().addResource(with: .photo, fileURL: file, options: nil)
        }
    }

    /// Delete finished downloads (after sharing/saving, on sign-out).
    static func cleanUp() {
        try? FileManager.default.removeItem(at: folder)
    }
}

extension DownloadManager: URLSessionDownloadDelegate {
    func urlSession(_ session: URLSession, downloadTask: URLSessionDownloadTask, didFinishDownloadingTo location: URL) {
        let continuation = lock.withLock { continuations.removeValue(forKey: downloadTask.taskIdentifier) }
        let status = (downloadTask.response as? HTTPURLResponse)?.statusCode ?? 0
        guard status == 200 else {
            continuation?.resume(throwing: status == 403 ? Failure.noAccess : (status == 404 || status == 410 ? Failure.expired : Failure.server))
            return
        }
        do {
            try FileManager.default.createDirectory(at: Self.folder, withIntermediateDirectories: true,
                                                    attributes: [.protectionKey: FileProtectionType.complete])
            let name = PhotoCache.safe(downloadTask.taskDescription ?? "download")
            let ext = (downloadTask.response?.mimeType == "application/zip") ? "zip" : "jpg"
            let target = Self.folder.appending(path: "\(name).\(ext)")
            try? FileManager.default.removeItem(at: target)
            try FileManager.default.moveItem(at: location, to: target)
            try (target as NSURL).setResourceValue(FileProtectionType.complete, forKey: .fileProtectionKey)
            continuation?.resume(returning: target)
        } catch {
            continuation?.resume(throwing: Failure.server)
        }
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        guard let error else { return }
        let continuation = lock.withLock { continuations.removeValue(forKey: task.taskIdentifier) }
        continuation?.resume(throwing: (error as? URLError) != nil ? Failure.network : error)
    }

    func urlSessionDidFinishEvents(forBackgroundURLSession session: URLSession) {
        DispatchQueue.main.async { [self] in backgroundCompletion?(); backgroundCompletion = nil }
    }
}
