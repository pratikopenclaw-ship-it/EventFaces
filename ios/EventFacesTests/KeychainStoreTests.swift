import Foundation
import Security
import Testing
@testable import EventFaces

@Suite("Keychain", .serialized)
struct KeychainStoreTests {
    let store = KeychainStore(service: "app.eventfaces.tests.\(UUID().uuidString)")

    @Test func roundTripAndDelete() throws {
        defer { try? store.deleteAll() }
        try store.set(Data("secret".utf8), for: "k")
        #expect(try store.data(for: "k") == Data("secret".utf8))
        try store.set(Data("new".utf8), for: "k")  // overwrite
        #expect(try store.data(for: "k") == Data("new".utf8))
        try store.delete("k")
        #expect(try store.data(for: "k") == nil)
    }

    @Test func itemsNeverLeaveThisDevice() throws {
        defer { try? store.deleteAll() }
        try store.set(Data("x".utf8), for: "k")
        #expect(try store.accessibility(of: "k") == (kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly as String))
    }

    @Test func deleteAllWipesOnlyThisService() throws {
        let other = KeychainStore(service: "app.eventfaces.tests.other.\(UUID().uuidString)")
        defer { try? other.deleteAll(); try? store.deleteAll() }
        try store.set(Data("a".utf8), for: "a")
        try other.set(Data("b".utf8), for: "b")
        try store.deleteAll()
        #expect(try store.data(for: "a") == nil)
        #expect(try other.data(for: "b") == Data("b".utf8))
    }
}
