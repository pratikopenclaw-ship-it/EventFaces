import XCTest

/// The screen matrix: key screens in light and dark, at the default and the largest
/// accessibility text size, on every simulator `test.sh` runs (small/large iPhone, iPad).
/// The oracle is `performAccessibilityAudit` (contrast, clipped text, Dynamic Type, hit
/// regions); screenshots are attached to the result bundle for human review.
@MainActor
final class ScreenMatrixUITests: XCTestCase {
    static let api = URL(string: "http://localhost:8000")!
    nonisolated(unsafe) var app: XCUIApplication!

    override func setUp() async throws {
        continueAfterFailure = false
        app = XCUIApplication()
    }

    override func tearDown() async throws {
        XCUIDevice.shared.appearance = .light
    }

    func testLightDefaultText() throws { try walk(.light, largestText: false) }
    func testDarkDefaultText() throws { try walk(.dark, largestText: false) }
    func testLightLargestText() throws { try walk(.light, largestText: true) }
    func testDarkLargestText() throws { try walk(.dark, largestText: true) }

    private func walk(_ appearance: XCUIDevice.Appearance, largestText: Bool) throws {
        let event = e2ePost("__e2e/event", expect: "code")
        let accessCode = try XCTUnwrap(event["code"] as? String)
        XCUIDevice.shared.appearance = appearance
        app.launchArguments = ["-ui-testing-reset"]
            + (largestText ? ["-UIPreferredContentSizeCategoryName", "UICTContentSizeCategoryAccessibilityXXXL"] : [])
        app.launch()

        try check("onboarding", app.buttons["onboarding-skip"])
        app.buttons["onboarding-skip"].tap()
        try check("home", app.buttons["join-event"])

        app.buttons["join-event"].tap()
        let email = "ui-matrix-\(UUID().uuidString.prefix(6).lowercased())@example.com"
        let field = app.textFields["email-field"]
        XCTAssertTrue(field.waitForExistence(timeout: 5))
        try check("sign-in", field)
        field.tap()
        field.typeText(email)
        tickTerms(app)  // Terms + 16+ (required)
        app.buttons["send-code"].tap()
        let codeField = app.textFields["code-field"]
        XCTAssertTrue(codeField.waitForExistence(timeout: 10))
        codeField.typeText(code(for: email))
        XCTAssertTrue(app.staticTexts["signed-in-email"].waitForExistence(timeout: 10))
        app.buttons["join-event"].tap()

        let accessField = app.textFields["access-code-field"]
        XCTAssertTrue(accessField.waitForExistence(timeout: 10))
        try check("join", accessField)
        accessField.tap()
        accessField.typeText(accessCode)
        app.buttons["join-with-code"].tap()

        try check("event", app.buttons["find-my-photos"])
        app.buttons["find-my-photos"].tap()
        try check("consent", app.descendants(matching: .any).matching(identifier: "consent-checkbox").firstMatch)
    }

    /// Waits for `anchor`, attaches a screenshot and audits the screen.
    private func check(_ screen: String, _ anchor: XCUIElement, line: UInt = #line) throws {
        XCTAssertTrue(anchor.waitForExistence(timeout: 15), "\(screen) didn't appear", line: line)
        let shot = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        shot.name = "\(screen)-\(name.filter(\.isLetter).suffix(24))"
        shot.lifetime = .keepAlways
        add(shot)
        try auditScreen(app, line: line)
    }

    private func code(for email: String) -> String {
        for _ in 0..<20 {
            let url = Self.api.appending(path: "__e2e/mail").appending(queryItems: [URLQueryItem(name: "to", value: email)])
            if let data = try? Data(contentsOf: url), let json = try? JSONSerialization.jsonObject(with: data) as? [String: String],
               let s = json["subject"] { return String(s.prefix(6)) }
            Thread.sleep(forTimeInterval: 0.5)
        }
        return ""
    }
}
