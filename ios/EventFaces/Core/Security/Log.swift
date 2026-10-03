import os

/// Logging rule: static messages and enum values only. Never interpolate tokens, codes,
/// emails, URLs with query strings, or image data (os.Logger keeps dynamic values private
/// by default, but the safest log line is the one that never contains them).
enum Log {
    static let app = Logger(subsystem: "app.eventfaces.ios", category: "app")
    static let auth = Logger(subsystem: "app.eventfaces.ios", category: "auth")
}
