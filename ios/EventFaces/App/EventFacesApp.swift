import SwiftUI

/// Background downloads (ZIPs) finish while the app is suspended.
final class AppDelegate: NSObject, UIApplicationDelegate {
    func application(_ application: UIApplication, didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil) -> Bool {
        MainActor.assumeIsolated { PushManager.shared.configure() }
        return true
    }

    func application(_ application: UIApplication, didRegisterForRemoteNotificationsWithDeviceToken deviceToken: Data) {
        MainActor.assumeIsolated { PushManager.shared.tokenHandler?(deviceToken) }
    }

    func application(_ application: UIApplication, handleEventsForBackgroundURLSession identifier: String, completionHandler: @escaping () -> Void) {
        if identifier == DownloadManager.sessionID { DownloadManager.shared.backgroundCompletion = completionHandler }
        if identifier == UploadManager.sessionID { UploadManager.shared.backgroundCompletion = completionHandler }
    }
}

@main
struct EventFacesApp: App {
    @UIApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @State private var model: AppModel
    @Environment(\.scenePhase) private var scenePhase

    init() {
        #if DEBUG
        if ProcessInfo.processInfo.arguments.contains("-ui-testing-reset") {
            try? KeychainStore().deleteAll()
            UserDefaults.standard.removePersistentDomain(forName: Bundle.main.bundleIdentifier ?? "")
        }
        #endif
        let session = SessionManager(store: KeychainStore())
        _model = State(initialValue: AppModel(auth: .live(session: session)))
    }

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(model)
                .preferredColorScheme(model.theme.colorScheme)
                .tint(Palette.accent)
                .task { await model.start() }
                .onOpenURL { url in Task { await model.open(url) } }
                .onContinueUserActivity(NSUserActivityTypeBrowsingWeb) { activity in
                    if let url = activity.webpageURL { Task { await model.open(url) } }
                }
                // Privacy: cover the content whenever the app isn't active, so the app
                // switcher snapshot never shows photos, emails or codes.
                .overlay { if scenePhase != .active { PrivacyShield() } }
                .overlay { if model.lock.locked && scenePhase == .active { LockScreen().environment(model) } }
                .onChange(of: scenePhase) { _, phase in if phase == .background { model.lock.didEnterBackground() } }
        }
    }
}
