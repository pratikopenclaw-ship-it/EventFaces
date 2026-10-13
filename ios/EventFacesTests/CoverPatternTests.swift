import Testing
@testable import EventFaces

/// Verifies the Swift port of the web's seeded PRNG (FNV-1a hash + mulberry32) against
/// values computed independently in Python with the same bit operations, so a translation
/// mistake (e.g. a missing 32-bit wrap) shows up as a mismatch rather than "looks plausible".
@Suite("Cover pattern (seeded like the web)")
struct CoverPatternTests {
    @Test func hashMatchesTheWebsDerivation() {
        #expect(CoverPattern.hashSeed("abc") == 440_920_331)
    }

    @Test func tilesMatchTheWebsPRNGSequence() {
        let tiles = CoverPattern.coverTiles(seed: "abc", count: 2)
        #expect(tiles.count == 2)
        #expect(abs(tiles[0].opacity - 0.21251762978732586) < 1e-9)
        #expect(abs(tiles[1].opacity - 0.14430354777723551) < 1e-9)
        #expect(tiles[0].found == false && tiles[1].found == false)
    }

    @Test func sameSeedIsDeterministic() {
        #expect(CoverPattern.coverTiles(seed: "same-event-id", count: 10).map(\.opacity)
            == CoverPattern.coverTiles(seed: "same-event-id", count: 10).map(\.opacity))
    }

    @Test func differentSeedsUsuallyDiffer() {
        let a = CoverPattern.coverTiles(seed: "event-one", count: 10).map(\.opacity)
        let b = CoverPattern.coverTiles(seed: "event-two", count: 10).map(\.opacity)
        #expect(a != b)
    }
}
