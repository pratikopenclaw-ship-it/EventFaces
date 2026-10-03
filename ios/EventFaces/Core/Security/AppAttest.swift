import CryptoKit
import DeviceCheck
import Foundation

/// Apple App Attest, behind a protocol so tests can stand in (the simulator has none).
protocol AttestationProvider: Sendable {
    var isSupported: Bool { get }
    func generateKey() async throws -> String
    func attestKey(_ keyID: String, clientDataHash: Data) async throws -> Data
    func generateAssertion(_ keyID: String, clientDataHash: Data) async throws -> Data
}

struct SystemAttestation: AttestationProvider {
    var isSupported: Bool { DCAppAttestService.shared.isSupported }

    func generateKey() async throws -> String {
        try await DCAppAttestService.shared.generateKey()
    }

    func attestKey(_ keyID: String, clientDataHash: Data) async throws -> Data {
        try await DCAppAttestService.shared.attestKey(keyID, clientDataHash: clientDataHash)
    }

    func generateAssertion(_ keyID: String, clientDataHash: Data) async throws -> Data {
        try await DCAppAttestService.shared.generateAssertion(keyID, clientDataHash: clientDataHash)
    }
}

/// Report-only App Attest: after sign-in the app attests a fresh key (the server records
/// the result), then adds an assertion over every device-signed refresh. Nothing in the
/// app depends on the outcome, and failures are never shown or retried in a loop.
enum AppAttest {
    static func sha256(_ data: Data) -> Data { Data(SHA256.hash(data: data)) }

    /// Attest once per session (the key id is wiped with the session on sign-out).
    static func attestIfNeeded(
        provider: any AttestationProvider,
        session: SessionManager,
        challenge: () async throws -> Data?,
        submit: (_ keyID: String, _ attestation: Data) async throws -> Bool
    ) async {
        guard provider.isSupported, await session.attestKeyID() == nil else { return }
        do {
            guard let challenge = try await challenge() else { return }  // the server has it off
            let keyID = try await provider.generateKey()
            let attestation = try await provider.attestKey(keyID, clientDataHash: sha256(challenge))
            if try await submit(keyID, attestation) { try await session.setAttestKeyID(keyID) }
        } catch {
            Log.auth.notice("App Attest: attestation not completed")
        }
    }
}
