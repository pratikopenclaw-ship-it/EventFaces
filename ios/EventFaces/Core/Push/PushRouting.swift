import Foundation

/// What a tapped notification asks the app to open. Payloads carry only ids (the backend's
/// `push.payload`): anything else, or anything malformed, is ignored.
enum PushRoute: Equatable, Sendable {
    case searchResults(eventID: String)
    case searchRejected(eventID: String)
    case moderation(eventID: String)

    static let kinds: Set<String> = ["search_ready", "search_rejected", "moderation_pending"]

    static func parse(_ userInfo: [AnyHashable: Any]) -> PushRoute? {
        guard let kind = userInfo["kind"] as? String, kinds.contains(kind),
              let raw = userInfo["event_id"] as? String, let uuid = UUID(uuidString: raw), raw.count == 36
        else { return nil }
        let id = uuid.uuidString.lowercased()
        switch kind {
        case "search_ready": return .searchResults(eventID: id)
        case "search_rejected": return .searchRejected(eventID: id)
        default: return .moderation(eventID: id)
        }
    }
}

/// Device token → hex, as the API expects (and validates).
enum PushToken {
    static func hex(_ token: Data) -> String { token.map { String(format: "%02x", $0) }.joined() }

    static var environment: String {
        #if DEBUG
        "sandbox"
        #else
        "production"
        #endif
    }
}
