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

    // The shared helper retries: seeding an event indexes its photos in the request, which
    // can outlast one 10 s attempt right after a search.
    private func post(_ path: String, expect key: String? = nil) -> [String: Any] { e2ePost(path, expect: key) }

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
        let event = post("__e2e/event", expect: "code")
        let accessCode = try XCTUnwrap(event["code"] as? String)
        launchSignedIn()

        app.buttons["join-event"].tap()
        let codeField = app.textFields["access-code-field"]
        XCTAssertTrue(codeField.waitForExistence(timeout: 5))
        codeField.tap()
        codeField.typeText(accessCode)
        tapWhenSettled(app, app.buttons["join-with-code"])

        try consentAndCapture()
        // The fake camera shows front, left, right as the steps ask; guidance captures each.
        XCTAssertTrue(app.staticTexts["results-title"].waitForExistence(timeout: 90))
        XCTAssertEqual(app.staticTexts["results-title"].label, "You're in 2 photos")
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

    /// Photos the organizers shared (no faces) open from the event screen without consent
    /// or a selfie, in the same grid and viewer, minus verdicts, shortlist and "missing".
    func testSharedEventPhotosNeedNoSelfie() throws {
        _ = post("__e2e/reset")
        let event = post("__e2e/event", expect: "code")
        let eventID = try XCTUnwrap(event["id"] as? String)
        let accessCode = try XCTUnwrap(event["code"] as? String)
        let shared = try XCTUnwrap(post("__e2e/event/\(eventID)/shared-photo", expect: "id")["id"] as? String)
        launchSignedIn()

        app.buttons["join-event"].tap()
        let codeField = app.textFields["access-code-field"]
        XCTAssertTrue(codeField.waitForExistence(timeout: 5))
        codeField.tap()
        codeField.typeText(accessCode)
        tapWhenSettled(app, app.buttons["join-with-code"])

        let open = app.buttons["event-photos"]
        XCTAssertTrue(open.waitForExistence(timeout: 15))
        open.tap()
        let tile = app.buttons["photo-\(shared)"]
        XCTAssertTrue(tile.waitForExistence(timeout: 15))
        XCTAssertFalse(app.buttons["shortlist-\(shared)"].exists)
        XCTAssertFalse(app.buttons["shortlisted-only"].exists)
        XCTAssertFalse(app.buttons["missing"].exists)
        try audit()
        tile.tap()
        XCTAssertTrue(app.descendants(matching: .any)["viewer"].waitForExistence(timeout: 10))
        XCTAssertFalse(app.buttons["verdict-me"].exists)
        XCTAssertTrue(app.buttons["viewer-save"].exists)
        try audit()
        app.buttons["viewer-close"].tap()
        app.buttons["sheet-close"].tap()
        XCTAssertTrue(app.buttons["find-my-photos"].waitForExistence(timeout: 5))
    }

    func testAWrongAccessCodeIsExplained() throws {
        _ = post("__e2e/reset")
        _ = post("__e2e/event", expect: "code")
        launchSignedIn()
        app.buttons["join-event"].tap()
        let codeField = app.textFields["access-code-field"]
        XCTAssertTrue(codeField.waitForExistence(timeout: 5))
        codeField.tap()
        codeField.typeText("WRONG123")
        tapWhenSettled(app, app.buttons["join-with-code"])
        XCTAssertTrue(app.otherElements["join-error"].waitForExistence(timeout: 10) || app.staticTexts["That code didn't work. Check it and try again."].exists)
    }

    func testQRCodeLinkJoinsTheEvent() throws {
        _ = post("__e2e/reset")
        let event = post("__e2e/event", expect: "code")
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
        let event = post("__e2e/event", expect: "code")
        let accessCode = try XCTUnwrap(event["code"] as? String)
        launchSignedIn(["-fake-frame", "front=blurry"])
        app.buttons["join-event"].tap()
        let codeField = app.textFields["access-code-field"]
        XCTAssertTrue(codeField.waitForExistence(timeout: 5))
        codeField.tap()
        codeField.typeText(accessCode)
        tapWhenSettled(app, app.buttons["join-with-code"])
        try consentAndCapture()
        // The blurry front shot passes on-device guidance but the server rejects it, twice.
        XCTAssertTrue(app.otherElements["paused"].waitForExistence(timeout: 120) || app.staticTexts["Let's try that again"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["try-again"].exists)
    }
}
