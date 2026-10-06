import SwiftUI

/// An event's identity, as on the web (`frontend/src/components/event-cover.tsx`): a band in
/// the event's accent, topped by a "contact sheet" pattern seeded by the event id. The same
/// event shows the same pattern on the web and in the app (`EventCoverTests` pins the values).
/// The pattern fades out before the title, so the title always sits on solid accent.
enum CoverPattern {
    struct Tile: Equatable { let opacity: Double; let found: Bool }

    /// Port of the web's `coverTiles`: FNV-1a over UTF-16 units, then mulberry32. JavaScript's
    /// int32 maths (`Math.imul`, `>>>`, `| 0`) is wrapping UInt32 arithmetic here.
    static func tiles(seed: String, count: Int) -> [Tile] {
        var h: UInt32 = 2_166_136_261
        for unit in seed.utf16 { h = (h ^ UInt32(unit)) &* 16_777_619 }
        func next() -> Double {
            h = h &+ 0x6D2B_79F5
            var t = (h ^ (h >> 15)) &* (1 | h)
            t = (t &+ ((t ^ (t >> 7)) &* (61 | t))) ^ t
            return Double(t ^ (t >> 14)) / 4_294_967_296
        }
        return (0..<count).map { _ in
            let r = next()
            return Tile(opacity: 0.06 + r * 0.16, found: next() < 0.07)
        }
    }
}

/// The pattern strip: fixed-size tiles (wider screens get more, not bigger), fading out.
struct CoverPatternView: View {
    let seed: String
    let rows: Int
    let ink: Color

    private let tile = CGSize(width: 22, height: 16.5)
    private let gap: CGFloat = 6

    var body: some View {
        GeometryReader { geo in
            let columns = max(1, Int((geo.size.width - 24 + gap) / (tile.width + gap)))
            let width = (geo.size.width - 24 - CGFloat(columns - 1) * gap) / CGFloat(columns)
            let tiles = CoverPattern.tiles(seed: seed, count: columns * rows)
            VStack(alignment: .leading, spacing: gap) {
                ForEach(0..<rows, id: \.self) { row in
                    HStack(spacing: gap) {
                        ForEach(0..<columns, id: \.self) { col in
                            let t = tiles[row * columns + col]
                            RoundedRectangle(cornerRadius: 3)
                                .fill(ink.opacity(t.found ? 0.55 : t.opacity))
                                .overlay {
                                    if t.found { RoundedRectangle(cornerRadius: 3).stroke(ink, lineWidth: 2).padding(-2) }
                                }
                                .frame(width: width, height: width * 0.75)
                        }
                    }
                }
            }
            .padding(12)
        }
        .mask(LinearGradient(stops: [.init(color: .black, location: 0.35), .init(color: .clear, location: 1)], startPoint: .top, endPoint: .bottom))
        .clipped()
        .accessibilityHidden(true)  // decoration
    }
}

/// Full-width header of an event screen.
struct EventCover<Extra: View>: View {
    let name: String
    let seed: String
    let accentHex: String?
    var subtitle: Text?
    var logo: UIImage?
    @ViewBuilder var extra: () -> Extra

    var body: some View {
        let accent = EventAccent.color(accentHex) ?? Palette.accent
        let onAccent = EventAccent.onColor(accentHex) ?? Palette.onAccent
        VStack(alignment: .leading, spacing: 0) {
            CoverPatternView(seed: seed, rows: 3, ink: onAccent).frame(height: 96)
            HStack(alignment: .bottom, spacing: 14) {
                if let logo { LogoChip(image: logo, size: 64, name: name) }
                VStack(alignment: .leading, spacing: 4) {
                    Text(name)
                        .font(.largeTitle.bold())
                        .accessibilityAddTraits(.isHeader)
                        .fixedSize(horizontal: false, vertical: true)
                    if let subtitle { subtitle.font(.subheadline) }
                    extra()
                }
                Spacer(minLength: 0)
            }
            .padding(.horizontal, 20)
            .padding(.bottom, 20)
        }
        .foregroundStyle(onAccent)
        .background(accent, in: .rect(cornerRadius: 24))
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("event-cover")
    }
}

extension EventCover where Extra == EmptyView {
    init(name: String, seed: String, accentHex: String?, subtitle: Text? = nil, logo: UIImage? = nil) {
        self.init(name: name, seed: seed, accentHex: accentHex, subtitle: subtitle, logo: logo) { EmptyView() }
    }
}

/// The top of an event card in lists.
struct EventCoverStrip: View {
    let seed: String
    let accentHex: String?

    var body: some View {
        CoverPatternView(seed: seed, rows: 2, ink: EventAccent.onColor(accentHex) ?? Palette.onAccent)
            .frame(height: 64)
            .background(EventAccent.color(accentHex) ?? Palette.accent)
    }
}

/// An event in a list: cover strip, then the card's content.
struct EventCard<Content: View>: View {
    let seed: String
    let accentHex: String?
    @ViewBuilder var content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            EventCoverStrip(seed: seed, accentHex: accentHex)
            VStack(alignment: .leading, spacing: 12) { content }.padding(20)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Palette.surface)
        .clipShape(.rect(cornerRadius: 16))
        .overlay(RoundedRectangle(cornerRadius: 16).stroke(Palette.border))
    }
}

struct LogoChip: View {
    let image: UIImage
    let size: CGFloat
    let name: String

    var body: some View {
        Image(uiImage: image)
            .resizable()
            .scaledToFit()
            .padding(6)
            .frame(width: size, height: size)
            .background(Palette.surface, in: .rect(cornerRadius: 12))
            .accessibilityLabel(Text("\(name) logo"))
    }
}
