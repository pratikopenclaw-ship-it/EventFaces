import XCTest

/// Recorded demo of Phase 1 (not part of the regular suite: run explicitly). Pauses so a
/// screen recording is watchable, and saves a screenshot per step to build/demo.
@MainActor
final class DemoWalkthrough: XCTestCase {
    static let api = URL(string: "http://localhost:8000")!
    static let out = ProcessInfo.processInfo.environment["DEMO_OUT"] ?? NSTemporaryDirectory()

    func shot(_ name: String, _ app: XCUIApplication) {
        Thread.sleep(forTimeInterval: 1.2)
        try? XCUIScreen.main.screenshot().pngRepresentation.write(to: URL(fileURLWithPath: "\(Self.out)/\(name).png"))
    }

    func code(for email: String) -> String {
        for _ in 0..<20 {
            let url = Self.api.appending(path: "__e2e/mail").appending(queryItems: [URLQueryItem(name: "to", value: email)])
            if let data = try? Data(contentsOf: url),
               let json = try? JSONSerialization.jsonObject(with: data) as? [String: String],
               let code = json["subject"]?.split(separator: " ").first { return String(code) }
            Thread.sleep(forTimeInterval: 0.5)
        }
        return ""
    }

    func testWalkthrough() {
        let app = XCUIApplication()
        app.launchArguments = ["-ui-testing-reset"]
        app.launch()
        shot("01-onboarding-1", app)
        app.buttons["onboarding-next"].tap(); shot("02-onboarding-2", app)
        app.buttons["onboarding-next"].tap(); shot("03-onboarding-3", app)
        app.buttons["onboarding-next"].tap(); shot("04-home-signed-out", app)

        app.buttons["home-sign-in"].tap()
        let email = "demo-\(UUID().uuidString.prefix(4).lowercased())@example.com"
        let field = app.textFields["email-field"]
        _ = field.waitForExistence(timeout: 5)
        field.tap(); field.typeText(email); shot("05-sign-in-email", app)
        tickTerms(app)  // Terms + 16+ (required)
        app.buttons["send-code"].tap()
        let codeField = app.textFields["code-field"]
        _ = codeField.waitForExistence(timeout: 10)
        shot("06-sign-in-code", app)
        codeField.typeText(code(for: email))
        _ = app.staticTexts["signed-in-email"].waitForExistence(timeout: 10)
        shot("07-home-signed-in", app)

        app.buttons["open-settings"].tap(); shot("08-settings-light", app)
        app.buttons["theme-dark"].tap(); shot("09-settings-dark", app)
        app.buttons["settings-done"].tap(); shot("10-home-dark", app)
        app.buttons["open-settings"].tap()
        app.swipeUp()
        app.buttons["sign-out"].tap()
        app.buttons["settings-done"].tap(); shot("11-signed-out-again", app)
    }
}
