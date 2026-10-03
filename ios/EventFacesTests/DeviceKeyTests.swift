import CryptoKit
import Foundation
import Testing
@testable import EventFaces

@Suite("Device key")
struct DeviceKeyTests {
    @Test func refreshMessageMatchesTheServer() {
        // Vector from backend app.services.mobile_auth.refresh_message (UUID lowercased there).
        let message = DeviceKey.refreshMessage(
            refreshToken: "test-refresh-token-0123456789abcdef",
            deviceID: UUID(uuidString: "3F2504E0-4F89-11D3-9A0C-0305E82C3301")!,
            timestamp: 1_790_000_000
        )
        #expect(String(decoding: message, as: UTF8.self)
            == "eventfaces-refresh|03d918a7bc97eb89a45a87de7d4be09d51c7823a7e01834a8df83e53726735be|3f2504e0-4f89-11d3-9a0c-0305e82c3301|1790000000")
    }

    @Test func keyPersistsAndSignaturesVerify() throws {
        let store = InMemorySecretStore()
        let signer = try DeviceKey.load(store: store)
        let again = try DeviceKey.load(store: store)
        #expect(signer.publicKeyBase64 == again.publicKeyBase64)  // same key after relaunch
        let raw = try #require(Data(base64Encoded: signer.publicKeyBase64))
        #expect(raw.count == 65 && raw.first == 0x04)  // X9.63 uncompressed point, as the API expects
        let message = Data("hello".utf8)
        let signature = try P256.Signing.ECDSASignature(derRepresentation: try #require(Data(base64Encoded: try signer.signatureBase64(for: message))))
        let publicKey = try P256.Signing.PublicKey(x963Representation: raw)
        #expect(publicKey.isValidSignature(signature, for: message))
    }

    @Test func wipingTheStoreMakesANewKey() throws {
        let store = InMemorySecretStore()
        let first = try DeviceKey.load(store: store).publicKeyBase64
        try store.deleteAll()
        #expect(try DeviceKey.load(store: store).publicKeyBase64 != first)
    }
}
