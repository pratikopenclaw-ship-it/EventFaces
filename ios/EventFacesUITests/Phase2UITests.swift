import XCTest

/// Join → consent → guided capture → results, on the simulator against the e2e API, with
/// the fake camera (the e2e server's test selfies).
@MainActor
final class Phase2UITests: XCTestCase {
    static let api = URL(string: "http://localhost:8000")!
    nonisolated(unsafe) var app: XCUIApplication!

    override func setUp() async throws {
        continueAfterFailure = false
        app = XCUIApplication()
    }

    private func post(_ path: String) -> [String: Any] {
        var r = URLRequest(url: Self.api.appending(path: path))
        r.httpMethod = "POST"
        let data = (try? NSURLConnectionLike.send(r)) ?? Data()
        return (try? JSONSerialization.jsonObject(with: data) as? [String: Any]) ?? [:]
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

    private func audit(line: UInt = #line) throws { try auditScreen(app, line: line) }

    private func launchSignedIn(_ extra: [String] = []) {
        app.launchArguments = ["-ui-testing-reset"] + extra
        app.launch()
        app.buttons["onboarding-skip"].tap()
        app.buttons["join-event"].tap()  // signed out: asks to sign in first
        let email = "ui-p2-\(UUID().uuidString.prefix(6).lowercased())@example.com"
        let field = app.textFields["email-field"]
        XCTAssertTrue(field.waitForExistence(timeout: 5))
        field.tap()
        field.typeText(email)
        tickTerms(app)  // Terms + 16+ (required)
        app.buttons["send-code"].tap()
        let codeField = app.textFields["code-field"]
        XCTAssertTrue(codeField.waitForExistence(timeout: 10))
        codeField.typeText(code(for: email))
        XCTAssertTrue(app.staticTexts["signed-in-email"].waitForExistence(timeout: 10))
    }

    private func consentAndCapture() throws {
        if !app.buttons["find-my-photos"].waitForExistence(timeout: 10) {
            let path = NSTemporaryDirectory() + "p2-\(name.filter(\.isLetter).suffix(30)).png"
            try? XCUIScreen.main.screenshot().pngRepresentation.write(to: URL(fileURLWithPath: path))
            print("P2 SCREEN: \(path)")
            XCTFail("no event screen after joining")
        }
        XCTAssertTrue(app.descendants(matching: .any)["event-cover"].exists, "the event's identity cover")
        app.buttons["find-my-photos"].tap()
        let checkbox = app.descendants(matching: .any).matching(identifier: "consent-checkbox").firstMatch
        XCTAssertTrue(checkbox.waitForExistence(timeout: 10))
        try audit()
        checkbox.tap()
        app.buttons["consent-continue"].tap()
        XCTAssertTrue(app.buttons["start-camera"].waitForExistence(timeout: 10))
        try audit()
        app.buttons["start-camera"].tap()
    }

    func testJoinByCodeConsentCaptureFindsYou() throws {
        _ = post("__e2e/reset")
        let event = post("__e2e/event")
        let accessCode = try XCTUnwrap(event["code"] as? String)
        launchSignedIn()

        app.buttons["join-event"].tap()
        let codeField = app.textFields["access-code-field"]
        XCTAssertTrue(codeField.waitForExistence(timeout: 5))
        codeField.tap()
        codeField.typeText(accessCode)
        app.buttons["join-with-code"].tap()

        try consentAndCapture()
        // The fake camera shows front, left, right as the steps ask; guidance captures each.
        XCTAssertTrue(app.staticTexts["results-title"].waitForExistence(timeout: 90))
        let headline = app.staticTexts["results-title"].label
        XCTAssertTrue(headline.range(of: #"^You're in \d+ photos?$"#, options: .regularExpression) != nil, headline)
        try resultsGalleryViewerAndDownloads()
    }

    /// Phase 3 on the same session: gallery → viewer → "Not me" → select → ZIP share sheet.
    private func resultsGalleryViewerAndDownloads() throws {
        let photos = app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH 'photo-'"))
        XCTAssertTrue(photos.firstMatch.waitForExistence(timeout: 20))
        assertTapTarget(app.buttons["select"])
        assertTapTarget(app.buttons["sheet-close"])
        let before = photos.count
        try audit()
        photos.firstMatch.tap()
        XCTAssertTrue(app.descendants(matching: .any)["viewer"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.buttons["viewer-close"].exists)
        assertTapTarget(app.buttons["viewer-close"])
        if before > 1 {
            // The filmstrip: tap the second photo to jump there.
            let strip = app.scrollViews["filmstrip"]
            XCTAssertTrue(strip.waitForExistence(timeout: 5))
            let second = strip.buttons["Photo 2"]
            assertTapTarget(second)
            second.tap()
            XCTAssertTrue(second.isSelected)
        }
        try audit()
        if app.buttons["verdict-not-me"].waitForExistence(timeout: 5) {
            app.buttons["verdict-not-me"].tap()
            if app.buttons["viewer-close"].exists { app.buttons["viewer-close"].tap() }
            XCTAssertTrue(NSPredicate(format: "count == %d", before - 1).evaluate(with: photos) || before == 1)
        } else {
            app.buttons["viewer-close"].tap()
        }
        if photos.count > 0 {
            app.buttons["select"].tap()
            photos.firstMatch.tap()
            XCTAssertTrue(app.buttons["download-all"].waitForExistence(timeout: 5))  // the bar slides in
            try audit()
            app.buttons["download-all"].tap()
            // The ZIP arrives through the share sheet (Save to Files, AirDrop…).
            XCTAssertTrue(app.otherElements["ActivityListView"].waitForExistence(timeout: 30) || app.navigationBars["UIActivityContentView"].waitForExistence(timeout: 5) || app.buttons["Save to Files"].waitForExistence(timeout: 5))
        }
    }

    func testAWrongAccessCodeIsExplained() throws {
        _ = post("__e2e/reset")
        _ = post("__e2e/event")
        launchSignedIn()
        app.buttons["join-event"].tap()
        let codeField = app.textFields["access-code-field"]
        XCTAssertTrue(codeField.waitForExistence(timeout: 5))
        codeField.tap()
        codeField.typeText("WRONG123")
        app.buttons["join-with-code"].tap()
        XCTAssertTrue(app.otherElements["join-error"].waitForExistence(timeout: 10) || app.staticTexts["That code didn't work. Check it and try again."].exists)
    }

    func testQRCodeLinkJoinsTheEvent() throws {
        _ = post("__e2e/reset")
        let event = post("__e2e/event")
        let slug = try XCTUnwrap(event["slug"] as? String), accessCode = try XCTUnwrap(event["code"] as? String)
        launchSignedIn(["-ui-testing-scan", "http://localhost:3000/join/\(slug)?code=\(accessCode)"])
        app.buttons["join-event"].tap()
        app.buttons["scan-qr"].tap()
        XCTAssertTrue(app.buttons["find-my-photos"].waitForExistence(timeout: 15))
    }

    func testAForeignQRCodeIsRefused() throws {
        launchSignedIn(["-ui-testing-scan", "https://evil.example/join/party?code=ABCD1234"])
        app.buttons["join-event"].tap()
        app.buttons["scan-qr"].tap()
        XCTAssertTrue(app.staticTexts["That QR code isn't an EventFaces event link."].waitForExistence(timeout: 10))
    }

    func testTwoRejectedSelfiesPauseWithTips() throws {
        _ = post("__e2e/reset")
        let event = post("__e2e/event")
        let accessCode = try XCTUnwrap(event["code"] as? String)
        launchSignedIn(["-fake-frame", "front=blurry"])
        app.buttons["join-event"].tap()
        let codeField = app.textFields["access-code-field"]
        XCTAssertTrue(codeField.waitForExistence(timeout: 5))
        codeField.tap()
        codeField.typeText(accessCode)
        app.buttons["join-with-code"].tap()
        try consentAndCapture()
        // The blurry front shot passes on-device guidance but the server rejects it, twice.
        XCTAssertTrue(app.otherElements["paused"].waitForExistence(timeout: 120) || app.staticTexts["Let's try that again"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["try-again"].exists)
    }
}
