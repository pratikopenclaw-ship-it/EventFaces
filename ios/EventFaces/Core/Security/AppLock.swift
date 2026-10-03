import Foundation
import LocalAuthentication
import Observation

/// Optional Face ID / Touch ID lock (Settings; off by default). When on, the app asks
/// again whenever it comes back after being in the background.
@MainActor
@Observable
final class AppLock {
    private let defaults: UserDefaults
    private(set) var locked = false
    var enabled: Bool {
        didSet { defaults.set(enabled, forKey: "app-lock") }
    }

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        enabled = defaults.bool(forKey: "app-lock")
        locked = enabled
    }

    var biometryName: String {
        let context = LAContext()
        _ = context.canEvaluatePolicy(.deviceOwnerAuthentication, error: nil)
        switch context.biometryType {
        case .faceID: return "Face ID"
        case .touchID: return "Touch ID"
        case .opticID: return "Optic ID"
        default: return "passcode"
        }
    }

    var isAvailable: Bool { LAContext().canEvaluatePolicy(.deviceOwnerAuthentication, error: nil) }

    func didEnterBackground() { if enabled { locked = true } }

    /// Biometrics with the device passcode as fallback.
    func unlock(reason: String) async {
        guard locked else { return }
        let context = LAContext()
        if (try? await context.evaluatePolicy(.deviceOwnerAuthentication, localizedReason: reason)) == true {
            locked = false
        }
    }

    /// Turning it on is confirmed with Face ID / Touch ID (so it can't lock someone out).
    func setEnabled(_ on: Bool, reason: String) async {
        if !on { enabled = false; locked = false; return }
        let context = LAContext()
        if (try? await context.evaluatePolicy(.deviceOwnerAuthentication, localizedReason: reason)) == true {
            enabled = true
        }
    }
}
