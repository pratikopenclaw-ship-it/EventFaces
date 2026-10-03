import CryptoKit
import Foundation

/// The device's signing key: the second factor of a session. The server binds the
/// session to its public key and refuses a refresh without a fresh signature, so a
/// refresh token copied off this phone is useless.
protocol DeviceSigner: Sendable {
    /// X9.63 uncompressed P-256 point, base64 (the format the API expects).
    var publicKeyBase64: String { get }
    func signatureBase64(for message: Data) throws -> String
}

enum DeviceKeyError: Error {
    case secureEnclaveUnavailable
}

/// Secure Enclave key (hardware, non-exportable). Only an opaque, device-bound handle is
/// stored in the Keychain; the private key never leaves the Enclave.
struct SecureEnclaveSigner: DeviceSigner {
    private let key: SecureEnclave.P256.Signing.PrivateKey

    init(store: SecretStore, account: String = "device-key") throws {
        guard SecureEnclave.isAvailable else { throw DeviceKeyError.secureEnclaveUnavailable }
        if let handle = try store.data(for: account), let existing = try? SecureEnclave.P256.Signing.PrivateKey(dataRepresentation: handle) {
            key = existing
        } else {
            key = try SecureEnclave.P256.Signing.PrivateKey(compactRepresentable: false)
            try store.set(key.dataRepresentation, for: account)
        }
    }

    var publicKeyBase64: String { key.publicKey.x963Representation.base64EncodedString() }

    func signatureBase64(for message: Data) throws -> String {
        try key.signature(for: message).derRepresentation.base64EncodedString()
    }
}

/// Software key in the Keychain (this device only). Used only where there is no Secure
/// Enclave: the simulator.
struct SoftwareSigner: DeviceSigner {
    private let key: P256.Signing.PrivateKey

    init(store: SecretStore, account: String = "device-key") throws {
        if let raw = try store.data(for: account), let existing = try? P256.Signing.PrivateKey(rawRepresentation: raw) {
            key = existing
        } else {
            key = P256.Signing.PrivateKey(compactRepresentable: false)
            try store.set(key.rawRepresentation, for: account)
        }
    }

    var publicKeyBase64: String { key.publicKey.x963Representation.base64EncodedString() }

    func signatureBase64(for message: Data) throws -> String {
        try key.signature(for: message).derRepresentation.base64EncodedString()
    }
}

enum DeviceKey {
    /// The Secure Enclave key on devices; a Keychain software key on the simulator only.
    static func load(store: SecretStore) throws -> DeviceSigner {
        #if targetEnvironment(simulator)
        if !SecureEnclave.isAvailable { return try SoftwareSigner(store: store) }
        #endif
        return try SecureEnclaveSigner(store: store)
    }

    /// What the device signs to refresh (must match backend `mobile_auth.refresh_message`).
    static func refreshMessage(refreshToken: String, deviceID: UUID, timestamp: Int) -> Data {
        let tokenHash = SHA256.hash(data: Data(refreshToken.utf8)).map { String(format: "%02x", $0) }.joined()
        return Data("eventfaces-refresh|\(tokenHash)|\(deviceID.uuidString.lowercased())|\(timestamp)".utf8)
    }
}
