import CoreGraphics
import Testing
@testable import EventFaces

/// The cover pattern must match the web's (`frontend/src/components/event-cover.tsx`
/// `coverTiles`) so an event looks the same everywhere. Expected values come from the web code.
struct EventCoverTests {
    typealias Tile = CoverPattern.Tile

    @Test func matchesTheWebForASimpleSeed() {
        let expected: [Tile] = [
            .init(opacity: 0.08199608519673347, found: true),
            .init(opacity: 0.06327750604599713, found: false),
            .init(opacity: 0.061841637939214704, found: false),
            .init(opacity: 0.1930818386748433, found: false),
            .init(opacity: 0.06880348958075047, found: false),
            .init(opacity: 0.18284686718136073, found: false),
        ]
        #expect(CoverPattern.tiles(seed: "event-a", count: 6) == expected)
    }

    @Test func matchesTheWebForAnEventID() {
        let expected: [Tile] = [
            .init(opacity: 0.17162119634449483, found: false),
            .init(opacity: 0.12219777300953866, found: false),
            .init(opacity: 0.21716916427016258, found: false),
            .init(opacity: 0.07014487825334072, found: true),
            .init(opacity: 0.18898282568901778, found: false),
            .init(opacity: 0.06786880314350129, found: false),
        ]
        #expect(CoverPattern.tiles(seed: "5810c1c5-c5b3-4a2b-9691-1245307ff9ca", count: 6) == expected)
    }

    @Test func differsPerEventAndIsStable() {
        let a = CoverPattern.tiles(seed: "event-a", count: 40)
        #expect(a == CoverPattern.tiles(seed: "event-a", count: 40))
        #expect(a != CoverPattern.tiles(seed: "event-b", count: 40))
        #expect(a.allSatisfy { (0.06...0.22).contains($0.opacity) })
    }
}

/// The results grid: justified rows like the web gallery.
struct JustifiedRowsTests {
    @Test func fullRowsFillTheWidthExactly() {
        let rows = JustifiedRows.rows(ratios: [1.5, 1.5, 0.75, 1.5, 1], width: 360, rowHeight: 120, spacing: 4)
        #expect(rows.map(\.indices) == [[0, 1], [2, 3, 4]])
        // Row 1: 1.5h + 1.5h + 4 = 360 → h = 118.67; every full row is exactly the width.
        let first = rows[0]
        #expect(abs(3 * first.height + 4 - 360) < 0.001)
        #expect(first.height <= 120)
    }

    @Test func theLastRowIsNotStretched() {
        let rows = JustifiedRows.rows(ratios: [1, 1], width: 360, rowHeight: 120, spacing: 4)
        #expect(rows.count == 1)
        #expect(rows[0].height == 120)  // two square photos don't blow up to 178 pt
    }

    @Test func everyPhotoIsPlacedOnce() {
        let ratios = (0..<37).map { CGFloat(0.5 + Double($0 % 5) * 0.5) }
        let rows = JustifiedRows.rows(ratios: ratios, width: 390, rowHeight: 120, spacing: 4)
        #expect(rows.flatMap(\.indices) == Array(0..<37))
        #expect(JustifiedRows.rows(ratios: ratios, width: 0, rowHeight: 120, spacing: 4).isEmpty)
    }
}
