import Foundation
import HTTPTypes
import OpenAPIRuntime

typealias EventSummary = Components.Schemas.EventListItem
typealias EventDetail = Components.Schemas.EventPublicOut
typealias ConsentInfo = Components.Schemas.ConsentInfo
typealias SelfieRequirements = Components.Schemas.SelfieRequirementsOut
typealias SearchResult = Components.Schemas.SearchOut
typealias SearchStatus = Components.Schemas.SearchStatusOut
typealias SyncStatusInfo = Components.Schemas.SyncStatusOut
typealias Member = Components.Schemas.MemberOut
typealias SearchLogRow = Components.Schemas.SearchLogRow
typealias ModerationItem = Components.Schemas.ModerationItem
typealias ReportItem = Components.Schemas.ReportOut
typealias RemovalItem = Components.Schemas.RemovalOut
typealias EventVideo = Components.Schemas.EventVideoOut

/// At-a-glance numbers for an event someone manages: the same four tiles as the web
/// dashboard, no management actions. Each tile degrades to nil on its own if that one
/// call fails (e.g. the Organizer Terms gate, surfaced separately by AuthMiddleware).
struct OrganizerStats: Sendable, Equatable {
    var publishedPhotos: Int?
    var facesFound: Int?
    var approvedMembers: Int?
    var pendingMembers: Int?
    var searchCount: Int?
    var matchRatePercent: Int?
    var needsAttention: Int?

    /// Pure aggregation (unit-testable without the network): each argument is nil if its
    /// own fetch failed, independently of the others.
    static func aggregate(
        sync: SyncStatusInfo?, members: [Member]?, searchLog: [SearchLogRow]?,
        queue: [ModerationItem]?, reports: [ReportItem]?, removals: [RemovalItem]?
    ) -> OrganizerStats {
        var stats = OrganizerStats()
        if let sync {
            stats.publishedPhotos = sync.publishedPhotos
            stats.facesFound = sync.faces
        }
        if let members {
            stats.approvedMembers = members.filter { $0.status == .approved }.count
            stats.pendingMembers = members.filter { $0.status == .pending }.count
        }
        if let searchLog {
            stats.searchCount = searchLog.count
            let matched = searchLog.filter { $0.matchCount > 0 }.count
            stats.matchRatePercent = searchLog.isEmpty ? nil : Int((Double(matched) / Double(searchLog.count) * 100).rounded())
        }
        var attention = 0
        var haveAttention = false
        if let queue { attention += queue.count; haveAttention = true }
        if let reports { attention += reports.count; haveAttention = true }
        if let removals { attention += removals.count; haveAttention = true }
        if haveAttention { stats.needsAttention = attention }
        return stats
    }
}

enum JoinError: Error, Equatable {
    case invalidCode
    case locked
    case inviteOnly
    case ended
    case revoked
    case inviteForAnotherEmail
    case inviteExpired
}

/// The outcome of submitting three selfies.
enum SearchOutcome: Equatable {
    case found(SearchResult)
    case queued
    case rejected(code: String, message: String, shot: String)
    case busy
    case alreadyQueued
    case consentRequired
    /// The single-use, 60-second capture token was spent or expired: get a new one.
    case captureTokenInvalid
}

/// Events, joining, consent and search: thin wrappers over the generated client that turn
/// HTTP outcomes into things the UI can explain.
struct EventService: Sendable {
    let api: Client
    let session: SessionManager
    let config: AppConfig
    let urlSession: URLSession

    func events() async throws -> [EventSummary] {
        switch try await call({ try await api.eventsListEvents() }) {
        case let .ok(ok): return try ok.body.json
        case let .undocumented(status, _): throw AuthService.error(status)
        }
    }

    func event(_ id: String) async throws -> EventDetail {
        switch try await call({ try await api.eventsGetEvent(path: .init(eventId: id)) }) {
        case let .ok(ok): return try ok.body.json
        case .unprocessableContent: throw AppError.server(status: 422)
        case let .undocumented(status, _): throw status == 403 ? AppError.noAccess : AuthService.error(status)
        }
    }

    func join(slug: String, code: String) async throws -> EventDetail {
        try await joined(call({ try await api.joinJoinByCode(body: .json(.init(code: code, slug: slug))) }))
    }

    func join(code: String) async throws -> EventDetail {
        try await joined(call({ try await api.joinJoinWithCodeOnly(body: .json(.init(code: code))) }))
    }

    private func joined<O>(_ output: O) throws -> EventDetail {
        switch output {
        case let o as Operations.JoinJoinByCode.Output:
            switch o {
            case let .ok(ok): return try ok.body.json
            case .unprocessableContent: throw JoinError.invalidCode
            case let .undocumented(status, payload): throw Self.joinError(status, payload)
            }
        case let o as Operations.JoinJoinWithCodeOnly.Output:
            switch o {
            case let .ok(ok): return try ok.body.json
            case .unprocessableContent: throw JoinError.invalidCode
            case let .undocumented(status, payload): throw Self.joinError(status, payload)
            }
        default: throw AppError.server(status: 0)
        }
    }

    static func joinError(_ status: Int, _ payload: UndocumentedPayload) -> Error {
        switch status {
        case 400: JoinError.invalidCode
        case 429: JoinError.locked
        case 403: JoinError.inviteOnly  // refined by the message in the UI only if needed
        default: AuthService.error(status)
        }
    }

    func acceptInvite(token: String) async throws -> EventDetail {
        switch try await call({ try await api.invitesAcceptInvite(body: .json(.init(token: token))) }) {
        case let .ok(ok):
            return try ok.body.json
        case .unprocessableContent: throw JoinError.inviteExpired
        case let .undocumented(status, _):
            switch status {
            case 403: throw JoinError.inviteForAnotherEmail
            case 400, 404, 410: throw JoinError.inviteExpired
            default: throw AuthService.error(status)
            }
        }
    }

    func consent() async throws -> ConsentInfo {
        switch try await call({ try await api.searchGetConsent() }) {
        case let .ok(ok): return try ok.body.json
        case let .undocumented(status, _): throw AuthService.error(status)
        }
    }

    func giveConsent(version: String) async throws -> ConsentInfo {
        switch try await call({ try await api.searchGiveConsent(body: .json(.init(version: version))) }) {
        case let .ok(ok): return try ok.body.json
        case .unprocessableContent: throw AppError.server(status: 422)
        case let .undocumented(status, _): throw AuthService.error(status)
        }
    }

    func selfieRequirements() async throws -> SelfieRequirements {
        switch try await call({ try await api.searchSelfieRequirements() }) {
        case let .ok(ok): return try ok.body.json
        case let .undocumented(status, _): throw AuthService.error(status)
        }
    }

    func captureToken(eventID: String) async throws -> String {
        switch try await call({ try await api.searchCaptureToken(path: .init(eventId: eventID)) }) {
        case let .ok(ok): return try ok.body.json.token
        case .unprocessableContent: throw AppError.server(status: 422)
        case let .undocumented(status, payload):
            if status == 403 {
                // "consent_required" (missing, or the text changed) or no access. The body of
                // an undocumented response isn't reliably readable through the generated
                // client, so ask the consent endpoint, which is authoritative.
                let body = try? await Data(collecting: payload.body ?? HTTPBody(), upTo: 64 * 1024)
                let detail = body.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }?["detail"] as? String
                if detail == "consent_required" { throw AppError.consentRequired }
                if let consent = try? await consent(), !consent.given { throw AppError.consentRequired }
                throw AppError.noAccess
            }
            throw AuthService.error(status)
        }
    }

    /// The three shots, concatenated, with the capture token: the same request the web's
    /// guided camera sends. The bytes live only in memory and are dropped by the caller.
    func search(eventID: String, captureToken: String, shots: [(name: String, jpeg: Data)]) async throws -> SearchOutcome {
        var body = Data()
        for shot in shots { body.append(shot.jpeg) }
        defer { body.withUnsafeMutableBytes { _ = $0.initializeMemory(as: UInt8.self, repeating: 0) } }
        var request = HTTPRequest(method: .post, scheme: nil, authority: nil, path: "/api/events/\(eventID)/search?source=camera")
        request.headerFields[.contentType] = "application/x-selfie-set"
        request.headerFields[HTTPField.Name("X-Capture-Token")!] = captureToken
        request.headerFields[HTTPField.Name("X-Selfie-Shots")!] = shots.map(\.name).joined(separator: ",")
        request.headerFields[HTTPField.Name("X-Selfie-Lengths")!] = shots.map { String($0.jpeg.count) }.joined(separator: ",")
        let (status, json) = try await raw(request, body: body)
        switch status {
        case 200: return .found(try JSONDecoder.api.decode(SearchResult.self, from: json))
        case 202: return .queued
        case 422:
            let object = (try? JSONSerialization.jsonObject(with: json) as? [String: Any]) ?? [:]
            return .rejected(code: object["code"] as? String ?? "", message: object["detail"] as? String ?? "", shot: object["shot"] as? String ?? "")
        case 503: return .busy
        case 409: return .alreadyQueued
        case 403:
            let object = (try? JSONSerialization.jsonObject(with: json) as? [String: Any]) ?? [:]
            switch object["detail"] as? String {
            case "consent_required": return .consentRequired
            case "capture_token_invalid": return .captureTokenInvalid
            default: throw AppError.noAccess
            }
        default: throw AuthService.error(status)
        }
    }

    func searchStatus(eventID: String) async throws -> SearchStatus {
        switch try await call({ try await api.searchSearchStatus(path: .init(eventId: eventID)) }) {
        case let .ok(ok): return try ok.body.json
        case .unprocessableContent: throw AppError.server(status: 422)
        case let .undocumented(status, _): throw AuthService.error(status)
        }
    }

    func myPhotos(eventID: String) async throws -> [String] {
        switch try await call({ try await api.searchMyPhotos(path: .init(eventId: eventID)) }) {
        case let .ok(ok): return try ok.body.json.map(\.id)
        case .unprocessableContent: throw AppError.server(status: 422)
        case let .undocumented(status, _): throw status == 403 ? AppError.noAccess : AuthService.error(status)
        }
    }

    /// Organizer-added video links (YouTube, Vimeo, Instagram, Google Drive). Read-only on
    /// iOS: adding/removing videos stays organizer-only on the web.
    func videos(eventID: String) async throws -> [EventVideo] {
        switch try await call({ try await api.eventsListEventVideos(path: .init(eventId: eventID)) }) {
        case let .ok(ok): return try ok.body.json
        case .unprocessableContent: throw AppError.server(status: 422)
        case let .undocumented(status, _): throw status == 403 ? AppError.noAccess : AuthService.error(status)
        }
    }

    /// An image the API streams (thumbnails, logos); kept in memory only in Phase 2.
    func image(path: String) async throws -> Data {
        let request = HTTPRequest(method: .get, scheme: nil, authority: nil, path: path)
        let (status, data) = try await raw(request, body: nil)
        guard status == 200 else { throw status == 403 ? AppError.noAccess : AuthService.error(status) }
        return data
    }

    // MARK: - Organizer stats (read-only; management stays on the web)

    func organizerStats(_ id: String) async -> OrganizerStats {
        async let syncOut = try? call({ try await api.photosSyncStatus(path: .init(eventId: id)) })
        async let membersOut = try? call({ try await api.membersListMembers(path: .init(eventId: id)) })
        async let searchLogOut = try? call({ try await api.privacySearchLog(path: .init(eventId: id)) })
        async let queueOut = try? call({ try await api.moderationModerationQueue(path: .init(eventId: id)) })
        async let reportsOut = try? call({ try await api.moderationListReports(path: .init(eventId: id)) })
        async let removalsOut = try? call({ try await api.privacyListRemovalRequests(path: .init(eventId: id)) })

        var sync: SyncStatusInfo?
        if case let .ok(ok) = await syncOut { sync = try? ok.body.json }
        var members: [Member]?
        if case let .ok(ok) = await membersOut { members = try? ok.body.json }
        var searchLog: [SearchLogRow]?
        if case let .ok(ok) = await searchLogOut { searchLog = try? ok.body.json }
        var queue: [ModerationItem]?
        if case let .ok(ok) = await queueOut { queue = try? ok.body.json }
        var reports: [ReportItem]?
        if case let .ok(ok) = await reportsOut { reports = try? ok.body.json }
        var removals: [RemovalItem]?
        if case let .ok(ok) = await removalsOut { removals = try? ok.body.json }

        return OrganizerStats.aggregate(sync: sync, members: members, searchLog: searchLog, queue: queue, reports: reports, removals: removals)
    }

    // MARK: -

    /// A request outside the generated client (raw bodies), through the same middleware
    /// rules: bearer token, app version, one refresh on 401.
    private func raw(_ request: HTTPRequest, body: Data?) async throws -> (Int, Data) {
        var urlRequest = URLRequest(url: URL(string: request.path ?? "/", relativeTo: config.apiBaseURL)!)
        urlRequest.httpMethod = request.method.rawValue
        for field in request.headerFields { urlRequest.setValue(field.value, forHTTPHeaderField: field.name.canonicalName) }
        urlRequest.setValue(config.appVersion, forHTTPHeaderField: "X-App-Version")
        urlRequest.httpBody = body
        func send(_ token: String?) async throws -> (Int, Data) {
            var r = urlRequest
            if let token { r.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
            let (data, response) = try await urlSession.data(for: r)
            return ((response as? HTTPURLResponse)?.statusCode ?? 0, data)
        }
        let token = try await session.validAccessToken()
        var result = try await send(token)
        if result.0 == 401, let token {
            result = try await send(try await session.refresh(replacing: token))
        }
        if result.0 == 426 { await session.reportUpdateRequired(nil) }
        return result
    }

    private func call<T>(_ op: () async throws -> T) async throws -> T {
        do { return try await op() } catch let error as ClientError { throw error.underlyingError }
    }
}
