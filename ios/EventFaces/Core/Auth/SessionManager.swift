import Foundation

/// What the API returns on sign-in and refresh.
struct SessionTokens: Sendable, Equatable {
    let accessToken: String
    let refreshToken: String
    let deviceID: UUID
}

enum SessionEvent: Sendable, Equatable {
    /// The server ended the session (logout elsewhere, password reset, revoked device,
    /// refresh-token reuse): local state is already wiped.
    case ended
    /// HTTP 426: this app version is no longer supported.
    case updateRequired(updateURL: URL?)
    /// HTTP 403 + X-Required-Action: the current Terms of Use (or Organizer Terms) must be
    /// accepted first.
    case acceptanceRequired(LegalDocumentKind)
}

/// Owns the session secrets.
///
/// - The access token lives in memory only (15 minutes; never written anywhere).
/// - The refresh token and device id live in the Keychain (this device only).
/// - Refreshes are single-flight: concurrent 401s wait for one refresh, so a rotated
///   refresh token is never presented twice (which the server treats as theft).
actor SessionManager {
    typealias Refresher = @Sendable (_ refresh: SignedRefresh) async throws -> SessionTokens

    private enum Key {
        static let refreshToken = "refresh-token"
        static let deviceID = "device-id"
        static let deviceKey = "device-key"
        static let attestKeyID = "attest-key-id"
    }

    private let store: SecretStore
    private let signerLoader: @Sendable (SecretStore) throws -> DeviceSigner
    private let clock: @Sendable () -> Date
    private var refresher: Refresher?
    private var attestation: (any AttestationProvider)?
    private var accessToken: String?
    private var refreshTask: Task<String, Error>?
    private var listeners: [@Sendable (SessionEvent) -> Void] = []

    init(
        store: SecretStore,
        signerLoader: @escaping @Sendable (SecretStore) throws -> DeviceSigner = { try DeviceKey.load(store: $0) },
        clock: @escaping @Sendable () -> Date = Date.init
    ) {
        self.store = store
        self.signerLoader = signerLoader
        self.clock = clock
    }

    func setRefresher(_ refresher: @escaping Refresher) { self.refresher = refresher }

    func setAttestation(_ provider: (any AttestationProvider)?) { attestation = provider }

    /// The App Attest key of this session (report-only), wiped with the other secrets.
    func attestKeyID() -> String? {
        (try? store.data(for: Key.attestKeyID)).flatMap { $0 }.map { String(decoding: $0, as: UTF8.self) }
    }

    func setAttestKeyID(_ keyID: String) throws { try store.set(Data(keyID.utf8), for: Key.attestKeyID) }

    func onEvent(_ listener: @escaping @Sendable (SessionEvent) -> Void) { listeners.append(listener) }

    /// The device key the server binds the next session to (created on first use).
    func devicePublicKey() throws -> String { try signerLoader(store).publicKeyBase64 }

    var hasSession: Bool { (try? store.data(for: Key.refreshToken)) != nil }

    func start(_ tokens: SessionTokens) throws {
        try store.set(Data(tokens.refreshToken.utf8), for: Key.refreshToken)
        try store.set(Data(tokens.deviceID.uuidString.lowercased().utf8), for: Key.deviceID)
        accessToken = tokens.accessToken
    }

    /// A usable access token, refreshing first if there is none in memory.
    func validAccessToken() async throws -> String? {
        if let accessToken { return accessToken }
        guard hasSession else { return nil }
        return try await refresh(replacing: nil)
    }

    /// Called after a 401 with `stale`: refresh once for everyone who saw that token.
    func refresh(replacing stale: String?) async throws -> String {
        if let current = accessToken, current != stale { return current }  // someone already refreshed
        if let running = refreshTask { return try await running.value }
        let task = Task { try await performRefresh() }
        refreshTask = task
        defer { refreshTask = nil }
        do {
            let token = try await task.value
            return token
        } catch {
            if error is SessionEndedError { endLocally(notify: true) }
            throw error
        }
    }

    private func performRefresh() async throws -> String {
        guard
            let refresher,
            let raw = try store.data(for: Key.refreshToken), let refreshToken = String(data: raw, encoding: .utf8),
            let rawID = try store.data(for: Key.deviceID), let deviceID = UUID(uuidString: String(decoding: rawID, as: UTF8.self))
        else { throw SessionEndedError() }
        let timestamp = Int(clock().timeIntervalSince1970)
        let signer = try signerLoader(store)
        let message = DeviceKey.refreshMessage(refreshToken: refreshToken, deviceID: deviceID, timestamp: timestamp)
        let signature = try signer.signatureBase64(for: message)
        let assertion = await assertion(over: message)
        let tokens = try await refresher(
            SignedRefresh(refreshToken: refreshToken, deviceID: deviceID, timestamp: timestamp, signature: signature, assertion: assertion)
        )
        try start(tokens)
        return tokens.accessToken
    }

    /// App Attest assertion over the refresh message, if this session attested a key.
    /// Report-only: any failure just leaves it out.
    private func assertion(over message: Data) async -> String? {
        guard let attestation, let keyID = attestKeyID() else { return nil }
        do {
            return try await attestation.generateAssertion(keyID, clientDataHash: AppAttest.sha256(message)).base64EncodedString()
        } catch {
            Log.auth.notice("App Attest: no assertion for this refresh")
            return nil
        }
    }

    func reportUpdateRequired(_ url: URL?) {
        for listener in listeners { listener(.updateRequired(updateURL: url)) }
    }

    func reportAcceptanceRequired(_ document: LegalDocumentKind) {
        for listener in listeners { listener(.acceptanceRequired(document)) }
    }

    /// Wipe every secret (sign-out, account deletion, server-ended session). The device
    /// key goes too: the next sign-in registers a fresh one.
    func endLocally(notify: Bool = false) {
        accessToken = nil
        refreshTask?.cancel()
        refreshTask = nil
        try? store.deleteAll()
        if notify { for listener in listeners { listener(.ended) } }
    }
}

/// What one device-signed refresh sends.
struct SignedRefresh: Sendable {
    let refreshToken: String
    let deviceID: UUID
    let timestamp: Int
    let signature: String
    let assertion: String?
}

/// The refresh was refused: the session is over and must not be retried.
struct SessionEndedError: Error, Equatable {}
