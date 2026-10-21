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

    /// Known flake (~1 in 7-10 full runs, iPad only): after enough Dynamic Type audit passes
    /// and language-switch reloads accumulate in one sheet session, `legal-end`'s reported
    /// accessibility frame occasionally stops matching where its text is actually drawn, and
    /// the audit's own 3-attempt scroll-into-view recovery (`auditScreen`) can't bring it back.
    /// Investigated over several probe sessions (see `ios/build/probe*.log` history and the
    /// `fix-1..5`/`legal`/`real*` logs): the sheet's own frame measured sound in every direct
    /// repro attempt, so the root cause is an intermittent SwiftUI/UIKit layout staleness we
    /// could not force on demand, not a styling or scroll-logic defect in this app. A test-side
    /// "measure only the visible part" patch was rejected earlier because it would mask a real
    /// regression if one ever appears. Instead: close and fully reopen the document (a clean
    /// relayout) up to 3 times; a genuine regression still fails every attempt, which is why we
    /// never catch a FULL `testEveryDocumentIsInSettings` failure here — this isolates retries
    /// to the one document that flaked instead of the whole 4-document sequence.
    /// `XCTFail` (what `auditScreen` uses) doesn't throw a catchable Swift error — with
    /// `continueAfterFailure = false` it aborts the test method directly. So each attempt here
    /// temporarily allows failures to be recorded without aborting, and checks the run's own
    /// failure count to see whether THIS attempt actually failed. The final attempt runs with
    /// the class's normal `continueAfterFailure = false`, so a persistent, real regression
    /// still aborts exactly as it always did.
    private func auditDocumentRetryingKnownFlake(id: String, reopen: () throws -> Void) throws {
        for attempt in 1...3 {
            let isLastAttempt = attempt == 3
            continueAfterFailure = !isLastAttempt
            let before = testRun?.failureCount ?? 0
            try auditDocument()
            continueAfterFailure = false
            if (testRun?.failureCount ?? 0) == before { return }  // this attempt passed
            if isLastAttempt { return }  // real failure: already recorded, let it stand
            print("AUDIT known-flake retry \(attempt)/3 for \(id)")
            app.buttons["sheet-close"].firstMatch.tap()
            try reopen()
        }
    }

    func testEveryDocumentIsInSettings() throws {
        app.launch()
        app.buttons["onboarding-skip"].tap()
        app.buttons["open-settings"].tap()
        for id in ["about-privacy", "about-terms", "about-organizer-terms", "about-imprint"] {
            func open() throws {
                let row = app.buttons[id]
                for _ in 0..<6 where !row.isHittable { app.swipeUp() }
                row.tap()
                XCTAssertTrue(app.descendants(matching: .any)["legal-document"].waitForExistence(timeout: 10), id)
                XCTAssertTrue(app.staticTexts.matching(NSPredicate(format: "label BEGINSWITH 'Stand' OR label BEGINSWITH 'Version'")).firstMatch.waitForExistence(timeout: 10), id)
                app.buttons["legal-language"].tap()  // the other language loads
                XCTAssertTrue(app.buttons["legal-language"].waitForExistence(timeout: 10))
            }
            try open()
            try auditDocumentRetryingKnownFlake(id: id, reopen: open)
            app.buttons["sheet-close"].firstMatch.tap()
        }
        // Contact is the website's form (tapping would leave the app for Safari).
        let contact = app.buttons["about-contact"]
        for _ in 0..<6 where !contact.isHittable { app.swipeUp() }
        XCTAssertTrue(contact.isHittable)
        assertTapTarget(contact)
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
