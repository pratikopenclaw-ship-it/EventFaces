import SwiftUI

/// Colour tokens from design/tokens.json (generated into Assets.xcassets/Colors by
/// scripts/gen-colors.py, light + dark). Never hard-code colours in views.
enum Palette {
    static let bg = Color("Bg")
    static let surface = Color("Surface")
    static let surface2 = Color("Surface2")
    static let border = Color("Border")
    static let text = Color("Text")
    static let textMuted = Color("TextMuted")
    static let accent = Color("Accent")
    static let accentHover = Color("AccentHover")
    static let onAccent = Color("OnAccent")
    static let accentSoft = Color("AccentSoft")
    /// Decorative only (2.1:1 in light mode): never the only cue.
    static let highlight = Color("Highlight")
    static let success = Color("Success")
    static let successText = Color("SuccessText")
    static let warningText = Color("WarningText")
    static let warningTint = Color("WarningTint")
    static let danger = Color("Danger")
    static let dangerText = Color("DangerText")

    /// Every token name, for the catalog-vs-tokens.json test.
    static let tokenNames = [
        "bg", "surface", "surface-2", "border", "text", "text-muted", "accent", "accent-hover", "on-accent",
        "accent-soft", "highlight", "success", "success-text", "warning-text", "warning-tint", "danger", "danger-text",
    ]

    static func assetName(for token: String) -> String {
        token.split(separator: "-").map { $0.prefix(1).uppercased() + $0.dropFirst() }.joined()
    }
}
