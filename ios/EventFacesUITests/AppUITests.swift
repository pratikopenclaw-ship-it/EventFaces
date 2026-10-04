import XCTest

/// End-to-end UI flows on the simulator against the local e2e API (test data only).
@MainActor
final class AppUITests: XCTestCase {
    static let api = URL(string: "http://localhost:8000")!
    nonisolated(unsafe) var app: XCUIApplication!

    override func setUp() async throws {
        continueAfterFailure = false
        app = XCUIApplication()
        app.launchArguments = ["-ui-testing-reset"]
    }

    private func audit(line: UInt = #line) throws { try auditScreen(app, line: line) }

    /// True once the element has keyboard focus (works with a hardware keyboard attached too).
    private func waitForFocus(_ element: XCUIElement, timeout: TimeInterval = 5) -> Bool {
        let focused = NSPredicate(format: "hasKeyboardFocus == true")
        return XCTWaiter().wait(for: [XCTNSPredicateExpectation(predicate: focused, object: element)], timeout: timeout) == .completed
    }

    private func skipOnboarding() {
        app.launch()
        app.buttons["onboarding-skip"].tap()
        XCTAssertTrue(app.staticTexts["Find your photos"].waitForExistence(timeout: 5))
    }

    private func latestCode(for email: String) throws -> String {
        let deadline = Date().addingTimeInterval(10)
        while Date() < deadline {
            let url = Self.api.appending(path: "__e2e/mail").appending(queryItems: [URLQueryItem(name: "to", value: email)])
            if let data = try? Data(contentsOf: url),
               let json = try? JSONSerialization.jsonObject(with: data) as? [String: String],
               let code = json["subject"]?.split(separator: " ").first {
                return String(code)
            }
            Thread.sleep(forTimeInterval: 0.5)
        }
        throw XCTSkip("no mail for \(email) (is the e2e API running?)")
    }

    func testOnboardingCanBeSkippedAndIsAccessible() throws {
        app.launch()
        XCTAssertTrue(app.buttons["onboarding-skip"].waitForExistence(timeout: 5))
        assertTapTarget(app.buttons["onboarding-skip"])
        try audit()
        app.buttons["onboarding-next"].tap()
        app.buttons["onboarding-next"].tap()
        app.buttons["onboarding-next"].tap()  // "Get started"
        XCTAssertTrue(app.staticTexts["Find your photos"].waitForExistence(timeout: 5))
        try audit()
    }

    func testPasswordlessSignInThemeAndSignOut() throws {
        var reset = URLRequest(url: Self.api.appending(path: "__e2e/reset"))
        reset.httpMethod = "POST"
        _ = try? NSURLConnectionLike.send(reset)
        let email = "ui-\(UUID().uuidString.prefix(8).lowercased())@example.com"

        skipOnboarding()
        app.buttons["home-sign-in"].tap()
        let field = app.textFields["email-field"]
        XCTAssertTrue(field.waitForExistence(timeout: 5))
        assertTapTarget(app.buttons["sign-in-cancel"])
        try audit()
        field.tap()
        field.typeText(email)
        tickTerms(app)  // Terms + 16+ (required)
        app.buttons["send-code"].tap()

        let codeField = app.textFields["code-field"]
        XCTAssertTrue(codeField.waitForExistence(timeout: 10))
        XCTAssertTrue(waitForFocus(codeField), "the code field should take the keyboard")
        codeField.typeText(try latestCode(for: email))  // six digits submit automatically
        XCTAssertTrue(app.staticTexts["signed-in-email"].waitForExistence(timeout: 10))
        XCTAssertEqual(app.staticTexts["signed-in-email"].label, email)

        assertTapTarget(app.buttons["open-settings"])
        app.buttons["open-settings"].tap()
        assertTapTarget(app.buttons["settings-done"])
        app.buttons["theme-dark"].tap()
        XCTAssertTrue(app.buttons["theme-dark"].isSelected)
        XCTAssertFalse(app.buttons["theme-system"].isSelected)
        try audit()

        app.buttons["sign-out"].tap()
        app.buttons["settings-done"].tap()
        XCTAssertTrue(app.buttons["home-sign-in"].waitForExistence(timeout: 5))
    }

    func testAWrongCodeIsExplained() throws {
        let email = "ui-wrong-\(UUID().uuidString.prefix(6).lowercased())@example.com"
        skipOnboarding()
        app.buttons["home-sign-in"].tap()
        let field = app.textFields["email-field"]
        XCTAssertTrue(field.waitForExistence(timeout: 5))
        field.tap()
        field.typeText(email)
        tickTerms(app)  // Terms + 16+ (required)
        app.buttons["send-code"].tap()
        let codeField = app.textFields["code-field"]
        XCTAssertTrue(codeField.waitForExistence(timeout: 10))
        XCTAssertTrue(waitForFocus(codeField), "the code field should take the keyboard")
        let real = try latestCode(for: email)
        codeField.typeText(real == "000000" ? "111111" : "000000")
        XCTAssertTrue(app.otherElements["sign-in-error"].waitForExistence(timeout: 10) || app.staticTexts["That code didn't work. Check it or send a new one."].exists)
    }
}

/// Synchronous POST for test setup.
enum NSURLConnectionLike {
    static func send(_ request: URLRequest) throws -> Data {
        final class Box: @unchecked Sendable { var data: Data? }
        let sem = DispatchSemaphore(value: 0)
        let box = Box()
        URLSession.shared.dataTask(with: request) { data, _, _ in box.data = data; sem.signal() }.resume()
        _ = sem.wait(timeout: .now() + 10)
        return box.data ?? Data()
    }
}
