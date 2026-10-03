import SwiftUI
import UIKit

/// Per-event organizer accents, made readable in both themes: the same rule as the web
/// (frontend/src/lib/accent.ts): nudge lightness toward black (light) or white (dark)
/// until the colour reaches 4.5:1 on every surface, then pick the on-accent text colour.
enum EventAccent {
    static let aa = 4.5
    static let surfaces: [ColorSchemeKey: [String]] = [
        .light: ["#FFFFFF", "#F3F7F6", "#E7EFED"],
        .dark: ["#171A21", "#0F1115", "#1E222B"],
    ]
    enum ColorSchemeKey { case light, dark }

    struct Pair: Equatable { let accent: String; let onAccent: String }

    static func readable(_ hex: String, for scheme: ColorSchemeKey) -> Pair? {
        guard let base = rgb(hex) else { return nil }
        let target: (Double, Double, Double) = scheme == .light ? (0, 0, 0) : (1, 1, 1)
        var color = base
        for step in 0...50 {
            let t = Double(step) / 50
            color = (base.0 + (target.0 - base.0) * t, base.1 + (target.1 - base.1) * t, base.2 + (target.2 - base.2) * t)
            // Check the colour as it will be drawn (rounded to 8-bit hex), not the exact maths.
            let drawn = rgb(hexString(color))!
            if surfaces[scheme]!.allSatisfy({ contrast(drawn, rgb($0)!) >= aa }) { break }
        }
        let candidates = [(1.0, 1.0, 1.0), rgb("#06201C")!]
        let on = candidates.max { contrast($0, color) < contrast($1, color) }!
        return Pair(accent: hexString(color), onAccent: hexString(on))
    }

    static func color(_ hex: String?) -> Color? {
        guard let hex, let light = readable(hex, for: .light), let dark = readable(hex, for: .dark) else { return nil }
        return Color(UIColor { $0.userInterfaceStyle == .dark ? UIColor(hex: dark.accent) : UIColor(hex: light.accent) })
    }

    static func onColor(_ hex: String?) -> Color? {
        guard let hex, let light = readable(hex, for: .light), let dark = readable(hex, for: .dark) else { return nil }
        return Color(UIColor { $0.userInterfaceStyle == .dark ? UIColor(hex: dark.onAccent) : UIColor(hex: light.onAccent) })
    }

    // MARK: WCAG maths

    static func rgb(_ hex: String) -> (Double, Double, Double)? {
        let h = hex.hasPrefix("#") ? String(hex.dropFirst()) : hex
        guard h.count == 6, let v = UInt32(h, radix: 16) else { return nil }
        return (Double((v >> 16) & 0xFF) / 255, Double((v >> 8) & 0xFF) / 255, Double(v & 0xFF) / 255)
    }

    static func luminance(_ c: (Double, Double, Double)) -> Double {
        func lin(_ x: Double) -> Double { x <= 0.04045 ? x / 12.92 : pow((x + 0.055) / 1.055, 2.4) }
        return 0.2126 * lin(c.0) + 0.7152 * lin(c.1) + 0.0722 * lin(c.2)
    }

    static func contrast(_ a: (Double, Double, Double), _ b: (Double, Double, Double)) -> Double {
        let (x, y) = (luminance(a), luminance(b))
        return (max(x, y) + 0.05) / (min(x, y) + 0.05)
    }

    static func hexString(_ c: (Double, Double, Double)) -> String {
        String(format: "#%02X%02X%02X", Int((c.0 * 255).rounded()), Int((c.1 * 255).rounded()), Int((c.2 * 255).rounded()))
    }
}

extension UIColor {
    convenience init(hex: String) {
        let c = EventAccent.rgb(hex) ?? (0, 0, 0)
        self.init(red: c.0, green: c.1, blue: c.2, alpha: 1)
    }
}
