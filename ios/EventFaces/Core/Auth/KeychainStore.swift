import Foundation
import Security

/// Where secrets live. Tests swap in an in-memory store.
protocol SecretStore: Sendable {
    func data(for key: String) throws -> Data?
    func set(_ data: Data, for key: String) throws
    func delete(_ key: String) throws
    func deleteAll() throws
}

enum KeychainError: Error, Equatable {
    case unexpectedStatus(OSStatus)
}

/// Generic-password Keychain items for this app only.
///
/// - `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`: never leaves this device (no
///   iCloud Keychain, not in backups that restore to another device), and readable after
///   the first unlock so background downloads and push deep links can refresh the session.
/// - `kSecAttrSynchronizable = false`: never synced.
struct KeychainStore: SecretStore {
    let service: String

    init(service: String = "app.eventfaces.session") {
        self.service = service
    }

    private func base(_ key: String) -> [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: key,
            kSecAttrSynchronizable as String: kCFBooleanFalse as Any,
        ]
    }

    func data(for key: String) throws -> Data? {
        var query = base(key)
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: AnyObject?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        if status == errSecItemNotFound { return nil }
        guard status == errSecSuccess else { throw KeychainError.unexpectedStatus(status) }
        return result as? Data
    }

    func set(_ data: Data, for key: String) throws {
        try delete(key)
        var attributes = base(key)
        attributes[kSecValueData as String] = data
        attributes[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        let status = SecItemAdd(attributes as CFDictionary, nil)
        guard status == errSecSuccess else { throw KeychainError.unexpectedStatus(status) }
    }

    func delete(_ key: String) throws {
        let status = SecItemDelete(base(key) as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else { throw KeychainError.unexpectedStatus(status) }
    }

    func deleteAll() throws {
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service]
        let status = SecItemDelete(query as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else { throw KeychainError.unexpectedStatus(status) }
    }

    /// The protection class actually stored (tests assert it).
    func accessibility(of key: String) throws -> String? {
        var query = base(key)
        query[kSecReturnAttributes as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: AnyObject?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        guard status == errSecSuccess, let attrs = result as? [String: Any] else { return nil }
        return attrs[kSecAttrAccessible as String] as? String
    }
}

/// For tests and previews.
final class InMemorySecretStore: SecretStore, @unchecked Sendable {
    private var items: [String: Data] = [:]
    private let lock = NSLock()

    func data(for key: String) throws -> Data? { lock.withLock { items[key] } }
    func set(_ data: Data, for key: String) throws { lock.withLock { items[key] = data } }
    func delete(_ key: String) throws { lock.withLock { items[key] = nil } }
    func deleteAll() throws { lock.withLock { items.removeAll() } }
    var isEmpty: Bool { lock.withLock { items.isEmpty } }
}
