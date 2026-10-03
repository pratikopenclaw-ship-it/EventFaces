import Foundation
import UIKit
import UserNotifications

/// Notification permission is asked only when it helps: when a search is queued and the
/// user taps "Notify me" (with an explanation first). The token is sent to the API for this
/// device only; signing out removes it on the server.
@MainActor
final class PushManager: NSObject, UNUserNotificationCenterDelegate {
    static let shared = PushManager()
    var onRoute: ((PushRoute) -> Void)?
    var tokenHandler: ((Data) -> Void)?
    private var pendingRoute: PushRoute?

    func configure() {
        UNUserNotificationCenter.current().delegate = self
    }

    var isAuthorized: Bool {
        get async {
            let settings = await UNUserNotificationCenter.current().notificationSettings()
            return settings.authorizationStatus == .authorized || settings.authorizationStatus == .provisional
        }
    }

    /// Ask (once the user chose to be notified) and register with APNs.
    func requestAndRegister() async -> Bool {
        let granted = (try? await UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound])) ?? false
        if granted { UIApplication.shared.registerForRemoteNotifications() }
        return granted
    }

    func registerIfAuthorized() async {
        if await isAuthorized { UIApplication.shared.registerForRemoteNotifications() }
    }

    /// A route from a cold start is delivered once the app is ready.
    func takePendingRoute() -> PushRoute? {
        defer { pendingRoute = nil }
        return pendingRoute
    }

    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse) async {
        // Parse here (userInfo isn't Sendable); only the validated route crosses actors.
        guard let route = PushRoute.parse(response.notification.request.content.userInfo) else { return }
        await MainActor.run {
            if let onRoute { onRoute(route) } else { pendingRoute = route }
        }
    }

    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification) async -> UNNotificationPresentationOptions {
        [.banner, .sound]
    }
}
