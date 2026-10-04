import Foundation
import HTTPTypes
import OpenAPIRuntime
import OpenAPIURLSession

/// URLSession for API calls: no cookies (the app authenticates with a bearer header only),
/// no response cache on disk, TLS 1.2+.
enum NetworkSession {
    static func make() -> URLSession {
        let config = URLSessionConfiguration.ephemeral
        config.httpCookieStorage = nil
        config.httpShouldSetCookies = false
        config.httpCookieAcceptPolicy = .never
        config.urlCache = nil
        config.requestCachePolicy = .reloadIgnoringLocalCacheData
        config.tlsMinimumSupportedProtocolVersion = .TLSv12
        config.timeoutIntervalForRequest = 30
        return URLSession(configuration: config)
    }
}

extension HTTPField.Name {
    static let appVersion = Self("X-App-Version")!
    static let requiredAction = Self("X-Required-Action")!
}

/// Adds the app version (the server answers 426 to unsupported versions) and the bearer
/// token; on 401 refreshes once and retries; on 426, or on 403 + X-Required-Action (terms to
/// accept), tells the session manager.
struct AuthMiddleware: ClientMiddleware {
    let session: SessionManager
    let appVersion: String
    /// Pre-login endpoints (sign-in, refresh) never carry a bearer token.
    var authenticate: Bool = true

    func intercept(
        _ request: HTTPRequest, body: HTTPBody?, baseURL: URL, operationID: String,
        next: @Sendable (HTTPRequest, HTTPBody?, URL) async throws -> (HTTPResponse, HTTPBody?)
    ) async throws -> (HTTPResponse, HTTPBody?) {
        var request = request
        request.headerFields[.appVersion] = appVersion
        request.headerFields[.acceptLanguage] = Locale.preferredLanguages.prefix(3).joined(separator: ", ")
        request.headerFields[.authorization] = nil
        request.headerFields[.cookie] = nil
        let token = authenticate ? try await session.validAccessToken() : nil
        if let token { request.headerFields[.authorization] = "Bearer \(token)" }

        // Keep a replayable copy of the body for the retry after a refresh.
        let bodyData: Data? = if let body { try await Data(collecting: body, upTo: 32 * 1024 * 1024) } else { nil }
        let (response, responseBody) = try await next(request, bodyData.map { HTTPBody($0) }, baseURL)

        if response.status.code == 426 {
            await session.reportUpdateRequired(await Self.updateURL(from: responseBody))
            return (response, nil)
        }
        guard response.status == .unauthorized, let token else { return await checked(response, responseBody) }
        let fresh = try await session.refresh(replacing: token)
        request.headerFields[.authorization] = "Bearer \(fresh)"
        let (retried, retriedBody) = try await next(request, bodyData.map { HTTPBody($0) }, baseURL)
        return await checked(retried, retriedBody)
    }

    private func checked(_ response: HTTPResponse, _ body: HTTPBody?) async -> (HTTPResponse, HTTPBody?) {
        if response.status == .forbidden, let action = response.headerFields[.requiredAction] {
            await session.reportAcceptanceRequired(action == "accept-organizer-terms" ? .organizerTerms : .terms)
        }
        return (response, body)
    }

    private static func updateURL(from body: HTTPBody?) async -> URL? {
        guard let body, let data = try? await Data(collecting: body, upTo: 64 * 1024),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let raw = json["update_url"] as? String, let url = URL(string: raw), url.scheme == "https"
        else { return nil }
        return url
    }
}

/// The generated client, configured for this app.
enum APIClientFactory {
    static func make(session: SessionManager, config: AppConfig = .current, urlSession: URLSession = NetworkSession.make(), authenticate: Bool = true) -> Client {
        make(session: session, config: config, transport: URLSessionTransport(configuration: .init(session: urlSession)), authenticate: authenticate)
    }

    static func make(session: SessionManager, config: AppConfig, transport: any ClientTransport, authenticate: Bool = true) -> Client {
        Client(
            serverURL: config.apiBaseURL,
            configuration: .init(dateTranscoder: FlexibleISO8601()),
            transport: transport,
            middlewares: [AuthMiddleware(session: session, appVersion: config.appVersion, authenticate: authenticate)]
        )
    }
}

/// The API sends microsecond timestamps ("2026-10-01T09:30:12.528837Z") and sometimes
/// none; accept both.
struct FlexibleISO8601: DateTranscoder {
    func encode(_ date: Date) throws -> String { date.formatted(.iso8601) }

    func decode(_ string: String) throws -> Date {
        if let date = try? Date(string, strategy: .iso8601.year().month().day().time(includingFractionalSeconds: true).timeZone(separator: .omitted)) { return date }
        if let date = try? Date(string, strategy: .iso8601) { return date }
        // Trim fractional digits beyond milliseconds, then retry.
        if let dot = string.firstIndex(of: "."), let end = string[dot...].firstIndex(where: { !$0.isNumber && $0 != "." }) {
            let trimmed = String(string[..<string.index(dot, offsetBy: min(4, string.distance(from: dot, to: end)))]) + string[end...]
            if let date = ISO8601DateFormatter.withFractions.date(from: trimmed) { return date }
        }
        throw DecodingError.dataCorrupted(.init(codingPath: [], debugDescription: "Unrecognised date"))
    }
}

private extension ISO8601DateFormatter {
    nonisolated(unsafe) static let withFractions: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()
}


extension JSONDecoder {
    /// For bodies read outside the generated client (generated types map snake_case keys).
    static var api: JSONDecoder {
        let d = JSONDecoder()
        d.dateDecodingStrategy = .custom { try FlexibleISO8601().decode(try $0.singleValueContainer().decode(String.self)) }
        return d
    }
}
