import SwiftUI

/// The event's identity decoration (ported from the web's `event-cover.tsx`): a grid of
/// faint tiles seeded by the event id, so the same event always draws the same pattern, a
/// few tiles standing in for "found" faces. Purely decorative.
struct CoverPattern: View {
    let seed: String
    /// 3 for the full event header, 2 for a card's cover strip.
    let rows: Int
    var tint: Color = Palette.onAccent

    // Enough tiles to fill `rows` rows even at the narrowest columns ever produced (22pt
    // tiles can't fit more than this many across any device). The web's equivalent
    // (`grid-template-columns: repeat(auto-fill, minmax(22px, 1fr))`) computes its actual
    // column count from the container's width; `.adaptive` is the SwiftUI equivalent — a
    // fixed column *count* (the previous bug) forced a ~1226pt-wide grid regardless of
    // screen width, pushing this view's content past the screen edge.
    private static let columns = 44

    var body: some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 22), spacing: 6)], spacing: 6) {
            ForEach(Array(tiles.enumerated()), id: \.offset) { _, tile in
                RoundedRectangle(cornerRadius: 3)
                    .fill(tint.opacity(tile.found ? 0.55 : tile.opacity))
                    .overlay {
                        if tile.found { RoundedRectangle(cornerRadius: 3).strokeBorder(tint, lineWidth: 2) }
                    }
                    .aspectRatio(4.0 / 3.0, contentMode: .fit)
            }
        }
        .padding(12)
        .mask(LinearGradient(stops: [.init(color: .black, location: 0.35), .init(color: .clear, location: 1)], startPoint: .top, endPoint: .bottom))
        .allowsHitTesting(false)
        .accessibilityHidden(true)
    }

    private var tiles: [(opacity: Double, found: Bool)] { Self.coverTiles(seed: seed, count: Self.columns * rows) }

    // MARK: - Deterministic pattern (mirrors the web's seeded PRNG exactly)

    static func coverTiles(seed: String, count: Int) -> [(opacity: Double, found: Bool)] {
        var rng = Mulberry32(seed: hashSeed(seed))
        var tiles: [(opacity: Double, found: Bool)] = []
        tiles.reserveCapacity(count)
        for _ in 0..<count {
            let r1 = rng.next()
            let r2 = rng.next()
            tiles.append((opacity: 0.06 + r1 * 0.16, found: r2 < 0.07))
        }
        return tiles
    }

    /// FNV-1a-style string hash (matches the web's seed derivation).
    static func hashSeed(_ s: String) -> UInt32 {
        var h: UInt32 = 2166136261
        for byte in s.utf8 {
            h ^= UInt32(byte)
            h = h &* 16777619
        }
        return h
    }

    /// mulberry32: the same tiny deterministic PRNG the web uses.
    private struct Mulberry32 {
        private var a: UInt32
        init(seed: UInt32) { a = seed }
        mutating func next() -> Double {
            a = a &+ 0x6D2B79F5
            var t = (a ^ (a >> 15)) &* (a | 1)
            t = t &+ ((t ^ (t >> 7)) &* (t | 61))
            return Double(t ^ (t >> 14)) / 4294967296.0
        }
    }
}
