import Foundation
import Observation
import SwiftUI

/// App-wide state. Views read it from the environment; all mutation happens here.
@MainActor
@Observable
final class AppModel {
    enum Account: Equatable {
        case unknown
        case signedOut
        case signedIn(User)
    }

    private(set) var account: Account = .unknown
    private(set) var updateURL: URL?
    private(set) var updateRequired = false
    private(set) var notice: Notice?
    /// A link opened before the user signed in or before its screen exists (joined in Phase 2).
    private(set) var pendingLink: DeepLink?
    var showSignIn = false
    // Opening a sheet moves on from the home screen: its status notice is stale then (and
    // would sit, dimmed and unreadable, behind an iPad form sheet).
    var showSettings = false { didSet { if showSettings { notice = nil } } }
    var hasSeenOnboarding: Bool {
        didSet { defaults.set(hasSeenOnboarding, forKey: Keys.onboarding) }
    }
    var theme: ThemePreference {
        didSet { defaults.set(theme.rawValue, forKey: Keys.theme) }
    }

    enum Notice: Equatable { case sessionEnded, linkExpired, signedIn, accountDeleted }

    let auth: AuthService
    let events: EventService
    let lock = AppLock()
    /// Set by a "your photos are ready" notification: the event screen opens its results.
    var openResultsFor: String?
    let config: AppConfig
    /// Navigation: events opened from the list, a link, a QR code or a code.
    var path: [String] = []
    /// Set by a "photos waiting for review" notification.
    var organizerPath: OrganizerRoute?
    private(set) var myEvents: [EventSummary] = []
    var showJoin = false { didSet { if showJoin { notice = nil } } }
    private(set) var linkError: LocalizedStringKey?
    private let defaults: UserDefaults

    private enum Keys {
        static let onboarding = "onboarding.seen"
        static let theme = "theme"  // not sensitive: also mirrored to the profile
    }

    init(auth: AuthService, config: AppConfig = .current, defaults: UserDefaults = .standard) {
        self.auth = auth
        self.config = config
        self.events = EventService(api: auth.api, session: auth.session, config: config, urlSession: NetworkSession.make())
        self.defaults = defaults
        hasSeenOnboarding = defaults.bool(forKey: Keys.onboarding)
        theme = defaults.string(forKey: Keys.theme).flatMap(ThemePreference.init(rawValue:)) ?? .system
    }

    func start() async {
        await auth.install()
        PushManager.shared.onRoute = { [weak self] route in self?.handle(route) }
        PushManager.shared.tokenHandler = { [weak self] token in
            guard let self, case .signedIn = self.account else { return }
            Task { try? await self.auth.registerPushToken(token) }
        }
        await auth.session.onEvent { [weak self] event in
            Task { @MainActor in self?.handle(event) }
        }
        guard await auth.session.hasSession else {
            account = .signedOut
            return
        }
        do {
            adopt(try await auth.me())
        } catch {
            account = .signedOut
        }
    }

    // MARK: Sign-in

    func handle(_ route: PushRoute) {
        guard case .signedIn = account else { return }
        switch route {
        case let .searchResults(id), let .searchRejected(id):
            path = [id]
            if case .searchResults = route { openResultsFor = id }
        case let .moderation(id):
            organizerPath = OrganizerRoute(eventID: id)
        }
    }

    /// After DELETE /api/me: nothing of the account stays on the device.
    func didDeleteAccount() async {
        await auth.session.endLocally()
        await PhotoCache.shared.purgeAll()
        DownloadManager.cleanUp()
        UploadManager.cleanUp()
        account = .signedOut
        myEvents = []
        path = []
        showSettings = false
        notice = .accountDeleted
    }

    func didSignIn(_ user: User) {
        adopt(user)
        showSignIn = false
        showSettings = false
        notice = .signedIn
    }

    func signOut() async {
        await auth.signOut()
        await PhotoCache.shared.purgeAll()  // no event photos stay on the device
        DownloadManager.cleanUp()
        UploadManager.cleanUp()
        account = .signedOut
        myEvents = []
        path = []
        notice = nil  // a "You're signed in." banner must not outlive the session
    }

    private func adopt(_ user: User) {
        account = .signedIn(user)
        theme = user.theme  // the profile wins: other devices see it too
        Task {
            await refreshEvents()
            await PushManager.shared.registerIfAuthorized()  // refresh the token for this account
            if let link = pendingLink { pendingLink = nil; await follow(link) }  // the link that made them sign in
            if let route = PushManager.shared.takePendingRoute() { handle(route) }
        }
    }

    func refreshEvents() async {
        guard case .signedIn = account else { myEvents = []; return }
        myEvents = (try? await events.events()) ?? myEvents
    }

    func joinWithCode(_ code: String) async throws {
        let event = try await events.join(code: code)
        await refreshEvents()
        path = [event.id]
    }

    func openEvent(_ id: String) { path = [id] }

    func makeFrameSource() -> FrameSource {
        #if DEBUG && targetEnvironment(simulator)
        return FakeFrameSource(base: config.apiBaseURL)  // the simulator has no camera
        #elseif DEBUG
        if ProcessInfo.processInfo.arguments.contains("-fake-camera") { return FakeFrameSource(base: config.apiBaseURL) }
        return CameraFrameSource()
        #else
        return CameraFrameSource()
        #endif
    }

    // MARK: Preferences

    func setTheme(_ newValue: ThemePreference) {
        theme = newValue
        guard case .signedIn = account else { return }
        Task { try? await auth.setTheme(newValue) }  // the local choice already applies
    }

    // MARK: Links

    func open(_ url: URL) async {
        guard let link = DeepLink.parse(url, allowedHost: config.appLinkHost) else {
            Log.app.notice("Ignored a link the app doesn't handle")
            return
        }
        await follow(link)
    }

    /// Joining needs an account: a link opened while signed out waits for the sign-in
    /// it triggers (sign-in at the moment of value), then continues.
    func follow(_ link: DeepLink) async {
        linkError = nil
        if case let .signIn(token) = link {
            do { didSignIn(try await auth.signIn(magicToken: token)) } catch { notice = .linkExpired }
            return
        }
        guard case .signedIn = account else {
            pendingLink = link
            showSignIn = true
            return
        }
        do {
            switch link {
            case let .join(slug, code?):
                let event = try await events.join(slug: slug, code: code)
                await refreshEvents()
                path = [event.id]
            case .join:
                showJoin = true  // a link without its code: ask for it
            case let .invite(token):
                let event = try await events.acceptInvite(token: token)
                await refreshEvents()
                path = [event.id]
            case let .event(id):
                path = [id.uuidString.lowercased()]
            case .signIn:
                break
            }
        } catch {
            linkError = JoinMessages.message(for: error)
        }
    }

    func dismissNotice() { notice = nil }

    private func handle(_ event: SessionEvent) {
        switch event {
        case .ended:
            account = .signedOut
            notice = .sessionEnded
        case let .updateRequired(url):
            updateURL = url
            updateRequired = true
        }
    }
}
