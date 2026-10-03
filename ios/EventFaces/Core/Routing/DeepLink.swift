import Foundation

/// The web links the app opens (Universal Links; see the AASA file the web serves).
/// Everything is validated strictly: anything unexpected is ignored, never "best-effort"
/// parsed, so a crafted link can't steer the app somewhere else.
enum DeepLink: Equatable, Sendable {
    case join(slug: String, code: String?)
    case invite(token: String)
    case signIn(token: String)
    case event(id: UUID)

    // Regex isn't Sendable, but these literals are immutable.
    nonisolated(unsafe) private static let slug = /^[a-z0-9-]{1,80}$/
    nonisolated(unsafe) private static let code = /^[A-Za-z0-9]{1,32}$/
    nonisolated(unsafe) private static let token = /^[A-Za-z0-9_-]{20,100}$/

    /// `allowedHost` is the configured web host. https only, except localhost in Debug.
    static func parse(_ url: URL, allowedHost: String) -> DeepLink? {
        guard let parts = URLComponents(url: url, resolvingAgainstBaseURL: false),
              let host = parts.host?.lowercased(), host == allowedHost.lowercased(),
              parts.user == nil, parts.password == nil
        else { return nil }
        #if DEBUG
        let local = host == "localhost"  // the docker-compose stack
        let schemeOK = (parts.scheme == "https" && parts.port == nil) || (local && ["http", "https"].contains(parts.scheme))
        #else
        let schemeOK = parts.scheme == "https" && parts.port == nil
        #endif
        guard schemeOK else { return nil }
        // Percent-encoded slashes, dot segments or empty segments mean someone is being clever.
        let rawPath = parts.percentEncodedPath
        guard !rawPath.contains("%2F"), !rawPath.contains("%2f"), !rawPath.contains("//") else { return nil }
        let segments = rawPath.split(separator: "/", omittingEmptySubsequences: false).dropFirst().map(String.init)
        guard !segments.contains(".."), !segments.contains(".") else { return nil }
        let query = Dictionary((parts.queryItems ?? []).map { ($0.name, $0.value ?? "") }, uniquingKeysWith: { first, _ in first })

        switch segments.count == 2 ? (segments[0], segments[1]) : ("", "") {
        case let ("join", s) where s.wholeMatch(of: slug) != nil:
            let c = query["code"]
            if let c, c.wholeMatch(of: code) == nil { return nil }
            return .join(slug: s, code: c)
        case let ("invite", t) where t.wholeMatch(of: token) != nil:
            return .invite(token: t)
        case let ("events", id):
            guard let uuid = UUID(uuidString: id), id.count == 36 else { return nil }
            return .event(id: uuid)
        case ("m", "signin"):
            guard let t = query["t"], t.wholeMatch(of: token) != nil else { return nil }
            return .signIn(token: t)
        default:
            return nil
        }
    }
}
