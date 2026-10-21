import Foundation

/// Build-time configuration from Info.plist (set per configuration in project.yml).
struct AppConfig: Sendable {
    let apiBaseURL: URL
    /// The web host whose links (join, invite, sign-in, event) open the app.
    let appLinkHost: String
    let appVersion: String

    /// The website's contact form (the app has no form of its own). "/" isn't an app-link
    /// path (aasa.ts), so it opens in Safari rather than back in the app.
    var contactURL: URL { URL(string: "https://\(appLinkHost)/#contact")! }

    static let current: AppConfig = {
        let info = Bundle.main.infoDictionary ?? [:]
        guard
            let raw = info["EFAPIBaseURL"] as? String,
            let url = URL(string: raw),
            let host = info["EFAppLinkHost"] as? String,
            let version = info["CFBundleShortVersionString"] as? String
        else {
            fatalError("EFAPIBaseURL / EFAppLinkHost / CFBundleShortVersionString missing from Info.plist")
        }
        return AppConfig(apiBaseURL: url, appLinkHost: host, appVersion: version)
    }()
}
