import SwiftUI

/// Verb-first primary action: accent fill, on-accent text, 50 pt tall (44 pt minimum).
struct PrimaryButtonStyle: ButtonStyle {
    @Environment(\.isEnabled) private var isEnabled

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.body.weight(.semibold))
            .padding(.vertical, 12)  // large text keeps clear of the edges
            .frame(maxWidth: .infinity, minHeight: 50)
            .padding(.horizontal, 16)
            // Disabled: a token pair (text-muted on surface-2, >= 4.5:1) instead of fading the
            // label, so it stays readable and still looks clearly inactive.
            .foregroundStyle(isEnabled ? Palette.onAccent : Palette.textMuted)
            .background(isEnabled ? (configuration.isPressed ? Palette.accentHover : Palette.accent) : Palette.surface2, in: .rect(cornerRadius: 12))
            .contentShape(.rect)
    }
}

struct SecondaryButtonStyle: ButtonStyle {
    @Environment(\.isEnabled) private var isEnabled

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.body.weight(.medium))
            .padding(.vertical, 12)
            .frame(maxWidth: .infinity, minHeight: 50)
            .padding(.horizontal, 16)
            .foregroundStyle(isEnabled ? Palette.text : Palette.textMuted)
            .background(configuration.isPressed ? Palette.surface2 : Palette.surface, in: .rect(cornerRadius: 12))
            .overlay(RoundedRectangle(cornerRadius: 12).stroke(Palette.border))
            .contentShape(.rect)
    }
}

/// Text and icon buttons outside a card: the label itself gets the 44 × 44 pt minimum and a
/// tap shape. (A `.frame` outside a Button grows the layout, not the tappable area.)
struct TapTargetButtonStyle: ButtonStyle {
    @Environment(\.isEnabled) private var isEnabled

    func makeBody(configuration: Configuration) -> some View {
        let label = configuration.label
            .frame(minWidth: 44, minHeight: 44)
            .contentShape(.rect)
            .opacity(configuration.isPressed ? 0.7 : 1)
        if isEnabled { label } else { label.foregroundStyle(Palette.textMuted) }  // readable, not faded
    }
}

extension ButtonStyle where Self == TapTargetButtonStyle {
    static var tapTarget: TapTargetButtonStyle { .init() }
}

extension ButtonStyle where Self == PrimaryButtonStyle {
    static var primary: PrimaryButtonStyle { .init() }
}

extension ButtonStyle where Self == SecondaryButtonStyle {
    static var secondary: SecondaryButtonStyle { .init() }
}

/// A message with an icon and text, so status never depends on colour alone.
struct Banner: View {
    enum Kind { case error, info, success }
    let kind: Kind
    let text: Text

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 10) {
            Image(systemName: symbol).accessibilityHidden(true)
            text.frame(maxWidth: .infinity, alignment: .leading)
        }
        .font(.subheadline)
        .foregroundStyle(foreground)
        .padding(12)
        .background(background, in: .rect(cornerRadius: 10))
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(kind == .error ? .isStaticText : [])
    }

    private var symbol: String {
        switch kind {
        case .error: "exclamationmark.triangle.fill"
        case .info: "info.circle.fill"
        case .success: "checkmark.circle.fill"
        }
    }

    private var foreground: Color {
        switch kind {
        case .error: Palette.dangerText
        case .info: Palette.text
        case .success: Palette.successText
        }
    }

    private var background: Color {
        switch kind {
        case .error: Palette.danger.opacity(0.1)
        case .info: Palette.accentSoft
        case .success: Palette.success.opacity(0.1)
        }
    }
}

struct Card<Content: View>: View {
    @ViewBuilder var content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: 12) { content }
            .padding(20)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Palette.surface, in: .rect(cornerRadius: 16))
            .overlay(RoundedRectangle(cornerRadius: 16).stroke(Palette.border))
    }
}

/// Readable column on iPad, full width on iPhone.
struct ReadableWidth: ViewModifier {
    func body(content: Content) -> some View {
        content.frame(maxWidth: 560).frame(maxWidth: .infinity)
    }
}

extension View {
    func readableWidth() -> some View { modifier(ReadableWidth()) }

    /// For screens under our own opaque header (sheets, full-screen flows): no iOS 26+ soft
    /// scroll-edge fade. It exists to keep content legible under glass bars; under an opaque
    /// header it only fades the first rows, which then fail contrast.
    @ViewBuilder func hardScrollEdges() -> some View {
        if #available(iOS 26, *) { scrollEdgeEffectHidden(true, for: .top) } else { self }
    }

    /// The root of every presented sheet / full-screen flow: hard scroll edges, plus an
    /// accessibility container whose frame is the sheet's real, visible frame (UI tests use
    /// it: on iPad a sheet stacked on a sheet reports a taller scroll view than it shows).
    /// `.contain` keeps the children's own identifiers (unlike an identifier on a plain stack).
    func sheetContent() -> some View {
        hardScrollEdges()
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("sheet-root")
    }
}
