import Foundation
import SwiftUI
import Testing
import UIKit
@testable import EventFaces

@Suite("Shipping configuration")
struct ConfigurationTests {
    func plist(_ name: String) throws -> [String: Any] {
        let data = try Data(contentsOf: repoRoot.appending(path: "ios/EventFaces/Resources/\(name)"))
        return try #require(try PropertyListSerialization.propertyList(from: data, format: nil) as? [String: Any])
    }

    /// "Contact us" opens the website's form; "/" is not an app-link path, so it stays in Safari.
    @Test func contactLinkIsTheWebsiteForm() {
        let config = AppConfig(apiBaseURL: URL(string: "https://eventfaces.example")!, appLinkHost: "eventfaces.example", appVersion: "1.0.0")
        #expect(config.contactURL.absoluteString == "https://eventfaces.example/#contact")
    }

    @Test func releaseHasNoATSExceptions() throws {
        #expect(try plist("Info.plist")["NSAppTransportSecurity"] == nil)
    }

    @Test func debugOnlyAllowsLocalNetworking() throws {
        var debug = try plist("Info-Debug.plist")
        let ats = try #require(debug.removeValue(forKey: "NSAppTransportSecurity") as? [String: Any])
        #expect(ats.count == 1 && ats["NSAllowsLocalNetworking"] as? Bool == true)
        // Otherwise identical to Release.
        #expect(NSDictionary(dictionary: debug).isEqual(to: try plist("Info.plist")))
    }

    @Test func releaseTalksHTTPSOnly() throws {
        let project = try String(contentsOf: repoRoot.appending(path: "ios/project.yml"), encoding: .utf8)
        // The app target's `Release:` settings block, not the top-level `Release: release`
        // config list (Debug's localhost URL comes right after that one).
        let lines = project.split(separator: "\n")
        let release = try #require(lines.firstIndex { $0.trimmingCharacters(in: .whitespaces) == "Release:" })
        let line = try #require(lines[release...].first { $0.contains("API_BASE_URL:") })
        #expect(line.contains("\"https://"))
    }

    @Test func privacyManifestShipsAndDeclaresNoTracking() throws {
        let url = try #require(Bundle(for: AppModelAnchor.self).url(forResource: "PrivacyInfo", withExtension: "xcprivacy")
            ?? Bundle.main.url(forResource: "PrivacyInfo", withExtension: "xcprivacy"))
        let manifest = try #require(try PropertyListSerialization.propertyList(from: Data(contentsOf: url), format: nil) as? [String: Any])
        #expect(manifest["NSPrivacyTracking"] as? Bool == false)
        #expect((manifest["NSPrivacyTrackingDomains"] as? [Any])?.isEmpty == true)
    }

    @Test func colourAssetsMatchTheSharedTokens() throws {
        let tokens = try #require(try JSONSerialization.jsonObject(with: Data(contentsOf: repoRoot.appending(path: "design/tokens.json"))) as? [String: Any])
        for theme in ["light", "dark"] {
            let values = try #require(tokens[theme] as? [String: String])
            #expect(Set(values.keys) == Set(Palette.tokenNames))
            let traits = UITraitCollection(userInterfaceStyle: theme == "dark" ? .dark : .light)
            for (token, hex) in values {
                let named = try #require(UIColor(named: Palette.assetName(for: token), in: .main, compatibleWith: traits), "\(token)")
                let color = named.resolvedColor(with: traits)
                var r: CGFloat = 0, g: CGFloat = 0, b: CGFloat = 0, a: CGFloat = 0
                color.getRed(&r, green: &g, blue: &b, alpha: &a)
                let actual = String(format: "#%02X%02X%02X", Int(round(r * 255)), Int(round(g * 255)), Int(round(b * 255)))
                #expect(actual == hex.uppercased(), "\(theme) \(token)")
            }
        }
    }

    @Test func germanTranslationsShip() throws {
        let path = try #require(Bundle.main.path(forResource: "de", ofType: "lproj"))
        let de = try #require(Bundle(path: path))
        #expect(de.localizedString(forKey: "Sign in", value: nil, table: nil) == "Anmelden")
        #expect(de.localizedString(forKey: "push.search_ready.title", value: nil, table: nil) == "Deine Fotos sind da")
        let enPath = try #require(Bundle.main.path(forResource: "en", ofType: "lproj"))
        let en = try #require(Bundle(path: enPath))
        #expect(en.localizedString(forKey: "push.search_ready.title", value: nil, table: nil) == "Your photos are ready")
    }
}

/// Lets tests find the app bundle.
final class AppModelAnchor {}
