import Foundation

/// Guest-photo uploads to the presigned storage URL on a background URLSession (they finish
/// if the app is suspended). The file is the user's own event photo in a protected temp
/// folder, deleted as soon as the upload ends.
final class UploadManager: NSObject, @unchecked Sendable {
    static let shared = UploadManager()
    static let sessionID = "app.eventfaces.uploads"

    enum Failure: Error, Equatable { case rejected(Int), network }

    private let lock = NSLock()
    private var continuations: [Int: CheckedContinuation<Void, Error>] = [:]
    private var progress: [Int: @Sendable (Double) -> Void] = [:]
    var backgroundCompletion: (() -> Void)?

    private lazy var session: URLSession = {
        let config = URLSessionConfiguration.background(withIdentifier: Self.sessionID)
        config.httpCookieStorage = nil
        config.httpShouldSetCookies = false
        config.urlCache = nil
        config.sessionSendsLaunchEvents = true
        return URLSession(configuration: config, delegate: self, delegateQueue: nil)
    }()

    static var folder: URL { FileManager.default.temporaryDirectory.appending(path: "EventFacesUploads", directoryHint: .isDirectory) }

    static func stage(_ data: Data, name: String) throws -> URL {
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true, attributes: [.protectionKey: FileProtectionType.complete])
        let url = folder.appending(path: "\(UUID().uuidString)-\(PhotoCache.safe(name))")
        try data.write(to: url, options: [.atomic, .completeFileProtection])
        return url
    }

    /// PUT the file to the presigned URL (no cookies, no bearer token: the URL is the credential).
    func put(file: URL, to url: URL, contentType: String, onProgress: @escaping @Sendable (Double) -> Void) async throws {
        var request = URLRequest(url: url)
        request.httpMethod = "PUT"
        request.setValue(contentType, forHTTPHeaderField: "Content-Type")
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            let task = session.uploadTask(with: request, fromFile: file)
            lock.withLock {
                continuations[task.taskIdentifier] = continuation
                progress[task.taskIdentifier] = onProgress
            }
            task.resume()
        }
    }

    static func cleanUp() { try? FileManager.default.removeItem(at: folder) }
}

extension UploadManager: URLSessionTaskDelegate {
    func urlSession(_ session: URLSession, task: URLSessionTask, didSendBodyData bytesSent: Int64, totalBytesSent: Int64, totalBytesExpectedToSend: Int64) {
        guard totalBytesExpectedToSend > 0 else { return }
        let report = lock.withLock { progress[task.taskIdentifier] }
        report?(Double(totalBytesSent) / Double(totalBytesExpectedToSend))
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        let continuation = lock.withLock { () -> CheckedContinuation<Void, Error>? in
            progress[task.taskIdentifier] = nil
            return continuations.removeValue(forKey: task.taskIdentifier)
        }
        if error != nil { continuation?.resume(throwing: Failure.network); return }
        let status = (task.response as? HTTPURLResponse)?.statusCode ?? 0
        if (200..<300).contains(status) { continuation?.resume() } else { continuation?.resume(throwing: Failure.rejected(status)) }
    }

    func urlSessionDidFinishEvents(forBackgroundURLSession session: URLSession) {
        DispatchQueue.main.async { [self] in backgroundCompletion?(); backgroundCompletion = nil }
    }
}
