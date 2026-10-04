import XCTest

/// Terms acceptance and the legal documents in the app, against the e2e API.
@MainActor
final class LegalUITests: XCTestCase {
    static let api = URL(string: "http://localhost:8000")!
    nonisolated(unsafe) var app: XCUIApplication!

    override func setUp() async throws {
        continueAfterFailure = false
        app = XCUIApplication()
        app.launchArguments = ["-ui-testing-reset"]
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

    /// The document view is audited (its heading, version line, language switch and the
    /// first sections: every paragraph below uses the same two text styles from the same
    /// view code), then scrolled to its end marker to prove the whole text renders.
    private func auditDocument() throws {
        try auditScreen(app)
        let end = app.descendants(matching: .any)["legal-end"]
        let scroll = app.descendants(matching: .any)["legal-document"].firstMatch
        for _ in 0..<60 where !(end.exists && scroll.frame.contains(end.frame)) {
            scroll.swipeUp()
        }
        XCTAssertTrue(end.exists && scroll.frame.contains(end.frame), "the end of the document should be reachable (end \(end.frame), visible \(scroll.frame))")
    }

    func testSignInNeedsTheTermsAndShowsThem() throws {
        app.launch()
        app.buttons["onboarding-skip"].tap()
        app.buttons["home-sign-in"].tap()
        let field = app.textFields["email-field"]
        XCTAssertTrue(field.waitForExistence(timeout: 5))
        field.tap()
        field.typeText("ui-legal@example.com")
        XCTAssertFalse(app.buttons["send-code"].isEnabled, "no code before the Terms are accepted")
        app.buttons["show-terms"].tap()
        XCTAssertTrue(app.descendants(matching: .any)["legal-document"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.staticTexts.matching(NSPredicate(format: "label BEGINSWITH '1. '")).firstMatch.waitForExistence(timeout: 10))
        try auditDocument()
        app.buttons["sheet-close"].firstMatch.tap()
        tickTerms(app)
        XCTAssertTrue(app.buttons["send-code"].isEnabled)
    }

    func testEveryDocumentIsInSettings() throws {
        app.launch()
        app.buttons["onboarding-skip"].tap()
        app.buttons["open-settings"].tap()
        for id in ["about-privacy", "about-terms", "about-organizer-terms", "about-imprint"] {
            let row = app.buttons[id]
            for _ in 0..<6 where !row.isHittable { app.swipeUp() }
            row.tap()
            XCTAssertTrue(app.descendants(matching: .any)["legal-document"].waitForExistence(timeout: 10), id)
            XCTAssertTrue(app.staticTexts.matching(NSPredicate(format: "label BEGINSWITH 'Stand' OR label BEGINSWITH 'Version'")).firstMatch.waitForExistence(timeout: 10), id)
            app.buttons["legal-language"].tap()  // the other language loads
            XCTAssertTrue(app.buttons["legal-language"].waitForExistence(timeout: 10))
            try auditDocument()
            app.buttons["sheet-close"].firstMatch.tap()
        }
    }

    func testChangedTermsAreAcceptedBeforeJoining() throws {
        _ = e2ePost("__e2e/reset")
        let event = e2ePost("__e2e/event", expect: "code")
        let accessCode = try XCTUnwrap(event["code"] as? String)
        let email = "ui-legal-\(UUID().uuidString.prefix(6).lowercased())@example.com"
        app.launch()
        app.buttons["onboarding-skip"].tap()
        app.buttons["home-sign-in"].tap()
        let field = app.textFields["email-field"]
        XCTAssertTrue(field.waitForExistence(timeout: 5))
        field.tap()
        field.typeText(email)
        tickTerms(app)
        app.buttons["send-code"].tap()
        let codeField = app.textFields["code-field"]
        XCTAssertTrue(codeField.waitForExistence(timeout: 10))
        codeField.typeText(code(for: email))
        XCTAssertTrue(app.staticTexts["signed-in-email"].waitForExistence(timeout: 10))

        // The Terms change (here: the acceptance is forgotten); the next event action asks.
        _ = e2ePost("__e2e/legal/reset", query: [URLQueryItem(name: "email", value: email)])
        app.buttons["join-event"].tap()
        let codeInput = app.textFields["access-code-field"]
        XCTAssertTrue(codeInput.waitForExistence(timeout: 5))
        codeInput.tap()
        codeInput.typeText(accessCode)
        app.buttons["join-with-code"].tap()

        let accept = app.buttons["accept-legal"]
        XCTAssertTrue(accept.waitForExistence(timeout: 15), "the acceptance sheet appears")
        XCTAssertFalse(accept.isEnabled)
        try auditScreen(app)
        let box = app.descendants(matching: .any)["accept-legal-checkbox"].firstMatch
        for _ in 0..<12 where !box.isHittable { app.swipeUp() }
        box.tap()
        accept.tap()
        XCTAssertTrue(accept.waitForNonExistence(timeout: 10))

        app.buttons["join-event"].tap()
        XCTAssertTrue(codeInput.waitForExistence(timeout: 5))
        codeInput.tap()
        codeInput.typeText(accessCode)
        app.buttons["join-with-code"].tap()
        XCTAssertTrue(app.buttons["find-my-photos"].waitForExistence(timeout: 15), "joined once accepted")
    }
}
