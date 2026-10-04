import UIKit
import XCTest

/// POST to the e2e server's control endpoints. Retries briefly: a freshly booted
/// simulator can refuse the first connections.
func e2ePost(_ path: String, query: [URLQueryItem] = [], expect key: String? = nil) -> [String: Any] {
    var request = URLRequest(url: URL(string: "http://localhost:8000")!.appending(path: path).appending(queryItems: query))
    request.httpMethod = "POST"
    for attempt in 0..<10 {
        if attempt > 0 { Thread.sleep(forTimeInterval: 1) }
        guard let data = try? NSURLConnectionLike.send(request),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { continue }
        if key == nil || json[key!] != nil { return json }
    }
    return [:]
}

@MainActor
extension XCTestCase {
    /// Ticks the sign-in Terms checkbox like a person would: if the keyboard covers it (large
    /// text, small phones), scroll the form first, which closes the keyboard.
    func tickTerms(_ app: XCUIApplication) {
        let box = app.descendants(matching: .any)["accept-terms"].firstMatch
        for _ in 0..<4 where app.keyboards.firstMatch.exists || !box.isHittable {
            app.scrollViews.firstMatch.swipeUp()
        }
        box.tap()
        let send = app.buttons["send-code"]
        for _ in 0..<4 where send.exists && !send.isHittable { app.scrollViews.firstMatch.swipeUp() }
    }

    /// The tappable area is at least 44 × 44 pt (Apple's minimum). A Button's accessibility
    /// frame is its label's frame, which is also what receives taps.
    func assertTapTarget(_ element: XCUIElement, file: StaticString = #filePath, line: UInt = #line) {
        XCTAssertTrue(element.exists, "\(element) missing", file: file, line: line)
        let frame = element.frame
        XCTAssertGreaterThanOrEqual(frame.width, 44, "'\(element.label)' is \(frame.width) pt wide", file: file, line: line)
        XCTAssertGreaterThanOrEqual(frame.height, 44, "'\(element.label)' is \(frame.height) pt tall", file: file, line: line)
    }

    /// Accessibility audit. Every issue fails, with one rule for overlap: an issue on an
    /// element that sits under the system's floating bars, the keyboard or the edge of its
    /// scroll view is re-checked with that element scrolled fully into view (keyboard
    /// dismissed), where it must pass. Nothing is filtered: every element is audited where it
    /// is fully visible. A contrast failure is checked against the rendered pixels and stands
    /// unless they measure at least 4.5:1 (`measuredContrast`).
    func auditScreen(_ app: XCUIApplication, line: UInt = #line) throws {
        // An element is identified by identifier and label together: two texts can share a
        // label (a document's version line at its top and its end marker).
        struct Key: Hashable { let id: String; let label: String }
        func key(_ e: XCUIElement?) -> Key { Key(id: e?.identifier ?? "", label: e?.label ?? "") }
        var deferred: [Key] = []  // overlapped in pass 1: each must pass fully in view
        var layout = Layout(app)  // queried once per audit: the issue handler must stay fast
        try audit(app) { issue in
            let verdict = self.measuredContrast(issue, in: app)
            if self.isOverlapped(issue.element, layout) || verdict == .notDrawn {
                let k = key(issue.element)
                if !deferred.contains(k) { deferred.append(k) }
                return true
            }
            if verdict == .passes { return true }
            self.report(issue, line: line)
            return false
        }
        guard !deferred.isEmpty else { return }
        print("AUDIT re-check fully in view: \(deferred.map(\.label))")
        dismissKeyboard(app)
        for k in deferred {
            // Unnamed elements get a clear-state audit (keyboard gone) with no scrolling.
            let target = k.label.isEmpty ? nil : app.descendants(matching: .any)
                .matching(NSPredicate(format: "label == %@ AND identifier == %@", k.label, k.id)).firstMatch
            // Up to three attempts, each with the element brought fully into view again: the
            // audit's own re-layout on iPad sheets is not deterministic, real problems are
            // (token colours don't flicker), so a genuine failure fails every attempt.
            var failures: [XCUIAccessibilityAuditIssue] = []
            for _ in 0..<3 {
                failures = []
                try audit(app, before: {
                    if let target, target.exists { self.scrollIntoView(target, in: app) }
                    layout = Layout(app)
                }) { issue in
                    let element = issue.element
                    let verdict = self.measuredContrast(issue, in: app)
                    if element == nil || key(element) == k {
                        // The element under re-check: it must pass where it is fully visible
                        // (still not drawn here fails too).
                        if verdict != .passes { failures.append(issue) }
                        return true
                    }
                    // Others: skipped only if hidden now (each was audited where it was in view).
                    if self.isOverlapped(element, layout) || verdict == .notDrawn || deferred.contains(key(element)) { return true }
                    if verdict != .passes { failures.append(issue) }
                    return true
                }
                if failures.isEmpty { break }
            }
            for issue in failures {
                report(issue, line: line)
                XCTFail("Accessibility audit: \(issue.compactDescription) on '\(issue.element?.label ?? "?")' (failed fully in view, 3 attempts)", line: line)
            }
        }
    }

    /// Every audit type, in two passes: Dynamic Type first (it temporarily changes text
    /// sizes, which re-lays out the screen and resets scroll positions), then all other
    /// types (contrast included) on the settled layout. Nothing is skipped.
    private func audit(_ app: XCUIApplication, before: () -> Void = {}, _ handler: @escaping (XCUIAccessibilityAuditIssue) -> Bool) throws {
        try app.performAccessibilityAudit(for: .dynamicType, handler)
        _ = XCTWaiter.wait(for: [XCTestExpectation(description: "layout settles")], timeout: 0.5)
        before()  // e.g. scroll the element under re-check into view, after the re-layout
        try app.performAccessibilityAudit(for: XCUIAccessibilityAuditType.all.subtracting(.dynamicType), handler)
    }

    /// Scrolls the element's scroll view with slow swipes until the element is fully inside
    /// its visible part (swiping back if it overshoots).
    private func scrollIntoView(_ element: XCUIElement, in app: XCUIApplication) {
        for _ in 0..<16 {
            let frame = element.frame
            let layout = Layout(app)
            guard let area = layout.innermostScroll(for: frame) else { return }
            let visible = area.insetBy(dx: 0, dy: 16)
            if visible.contains(frame) { break }
            // The scroll view element itself (the one whose frame holds the visible area).
            let scroll = app.scrollViews.allElementsBoundByIndex
                .filter { $0.frame.contains(CGPoint(x: area.midX, y: area.midY)) && $0.frame.minX <= frame.minX && $0.frame.maxX >= frame.maxX }
                .min { $0.frame.width * $0.frame.height < $1.frame.width * $1.frame.height }
            guard let scroll else { return }
            if frame.maxY > visible.maxY { scroll.swipeUp(velocity: 250) } else { scroll.swipeDown(velocity: 250) }
            _ = XCTWaiter.wait(for: [XCTestExpectation(description: "scroll settles")], timeout: 0.6)
        }
        // Let the scroll come to rest: the contrast check samples pixels.
        _ = XCTWaiter.wait(for: [XCTestExpectation(description: "scroll settles")], timeout: 1.0)
    }

    private func dismissKeyboard(_ app: XCUIApplication) {
        guard app.keyboards.firstMatch.exists else { return }
        app.swipeUp()  // forms close the keyboard on scroll (a swipe down would dismiss a sheet)
        // iPhone: "Done"; iPad: the dismiss key (its label varies by iOS version).
        let dismiss = app.keyboards.buttons.matching(NSPredicate(format: "label ==[c] 'Done' OR label CONTAINS[c] 'hide' OR label CONTAINS[c] 'dismiss' OR identifier CONTAINS[c] 'dismiss'")).firstMatch
        if app.keyboards.firstMatch.exists, dismiss.exists { dismiss.tap() }
        // On iPad the form sheet slides back down after the keyboard: measure once it has.
        _ = XCTWaiter.wait(for: [XCTestExpectation(description: "keyboard gone")], timeout: 1.2)
    }

    /// Under a system bar or the keyboard, or cut off by the edge of its scroll view (e.g.
    /// the bottom of a form sheet on iPad): the audit then measures what's behind it.
    private func isOverlapped(_ element: XCUIElement?, _ layout: Layout) -> Bool {
        guard let element else { return !layout.covers.isEmpty }  // unnamed: decide in the clear-state audit
        let frame = element.frame
        // Partly or wholly outside its scroll view (e.g. just below a form sheet's edge), or at
        // its edge, where the rest of its row is cut off under our header (the audit evaluates
        // the row but names the child), or off the window: audited where it is fully in view.
        let offscreen = !layout.window.contains(frame)
        let clipped = layout.innermostScroll(for: frame).map { !$0.insetBy(dx: 0, dy: 16).contains(frame) } ?? false
        return offscreen || clipped || layout.covers.contains { $0.intersects(frame) }
    }

    enum ContrastVerdict { case passes, fails, notDrawn, notMeasured }

    /// `.notDrawn`: no visible text in the element's frame at all (below 1.1:1), e.g. just past
    /// the visible edge of a nested sheet whose scroll view reports a taller frame. That is
    /// "not in view", re-checked scrolled into view, not a contrast verdict.
    private func measuredContrast(_ issue: XCUIAccessibilityAuditIssue, in app: XCUIApplication) -> ContrastVerdict {
        guard issue.auditType == .contrast, let element = issue.element, element.exists else { return .notMeasured }
        let shot = XCUIScreen.main.screenshot()
        guard let ratio = Self.renderedContrast(shot.image, frame: element.frame, points: app.windows.firstMatch.frame.width) else { return .notMeasured }
        let verdict: ContrastVerdict = ratio < 1.1 ? .notDrawn : ratio >= 4.5 ? .passes : .fails
        let attachment = XCTAttachment(screenshot: shot)
        attachment.name = "contrast-check \(element.label) \(String(format: "%.2f", ratio)):1"
        attachment.lifetime = .keepAlways
        add(attachment)
        print("AUDIT CONTRAST CHECK '\(element.label)': measured \(String(format: "%.2f", ratio)):1 (\(verdict))")
        return verdict
    }

    nonisolated static func renderedContrast(_ image: UIImage, frame: CGRect, points: CGFloat) -> Double? {
        guard let cg = image.cgImage, points > 0 else { return nil }
        let scale = CGFloat(cg.width) / points
        let rect = CGRect(x: frame.minX * scale, y: frame.minY * scale, width: frame.width * scale, height: frame.height * scale).integral
        guard let crop = cg.cropping(to: rect), crop.width > 0, crop.height > 0 else { return nil }
        let w = crop.width, h = crop.height
        var pixels = [UInt8](repeating: 0, count: w * h * 4)
        guard let ctx = CGContext(data: &pixels, width: w, height: h, bitsPerComponent: 8, bytesPerRow: w * 4,
                                  space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { return nil }
        ctx.draw(crop, in: CGRect(x: 0, y: 0, width: w, height: h))
        var counts: [UInt32: Int] = [:]
        for i in stride(from: 0, to: pixels.count, by: 4) {
            counts[UInt32(pixels[i]) << 16 | UInt32(pixels[i + 1]) << 8 | UInt32(pixels[i + 2]), default: 0] += 1
        }
        func luminance(_ c: UInt32) -> Double {
            func channel(_ v: UInt32) -> Double { let x = Double(v) / 255; return x <= 0.03928 ? x / 12.92 : pow((x + 0.055) / 1.055, 2.4) }
            return 0.2126 * channel(c >> 16 & 255) + 0.7152 * channel(c >> 8 & 255) + 0.0722 * channel(c & 255)
        }
        let total = pixels.count / 4
        func color(_ x: Int, _ y: Int) -> UInt32? {
            guard x >= 0, y >= 0, x < w, y < h else { return nil }
            let i = (y * w + x) * 4
            return UInt32(pixels[i]) << 16 | UInt32(pixels[i + 1]) << 8 | UInt32(pixels[i + 2])
        }
        let near = [(3, 0), (-3, 0), (0, 3), (0, -3), (6, 0), (-6, 0), (0, 6), (0, -6)]
        // Text is thin strokes: most of its pixels lie within a few pixels of another colour.
        // Backgrounds (the page, a box behind the text, its corners) are regions: most of
        // their pixels are surrounded by themselves.
        let significant = counts.filter { $0.value >= max(20, total / 200) }.keys
        var edgeShare: [UInt32: Double] = [:]
        var neighbours: [UInt32: [UInt32: Int]] = [:]
        for y in stride(from: 0, to: h, by: 2) {
            for x in stride(from: 0, to: w, by: 2) {
                guard let c = color(x, y), significant.contains(c) else { continue }
                var edge = false
                for (dx, dy) in near {
                    if let n = color(x + dx, y + dy), n != c {
                        edge = true
                        neighbours[c, default: [:]][n, default: 0] += 1
                    }
                }
                edgeShare[c, default: 0] += edge ? 1 : 0
            }
        }
        var samples: [UInt32: Double] = [:]
        for y in stride(from: 0, to: h, by: 2) { for x in stride(from: 0, to: w, by: 2) { if let c = color(x, y), significant.contains(c) { samples[c, default: 0] += 1 } } }
        // The most common colour is always a background: in a dense paragraph nearly every
        // background pixel lies close to a letter and would otherwise look like a stroke.
        var backgrounds = Set(significant.filter { (edgeShare[$0] ?? 0) / max(1, samples[$0] ?? 1) < 0.5 })
        if let dominant = counts.max(by: { $0.value < $1.value })?.key { backgrounds.insert(dominant) }
        let strokes = significant.filter { !backgrounds.contains($0) }
        guard !backgrounds.isEmpty else { return nil }  // no background region: can't tell, the audit's verdict stands
        // Text colours: strokes that make up a real share of all stroke pixels (each anti-aliasing
        // shade is a sliver); each is measured against the background it borders, weakest counts.
        let strokeTotal = strokes.reduce(0) { $0 + (counts[$1] ?? 0) }
        let text = strokes.filter { (counts[$0] ?? 0) * 100 >= strokeTotal * 15 }
        guard !text.isEmpty else { return 1 }  // nothing drawn in the frame
        var worst = Double.infinity
        for t in text {
            guard let bg = neighbours[t]?.filter({ backgrounds.contains($0.key) }).max(by: { $0.value < $1.value })?.key else { continue }
            let (lt, lb) = (luminance(t), luminance(bg))
            worst = min(worst, (max(lt, lb) + 0.05) / (min(lt, lb) + 0.05))
        }
        return worst.isFinite ? worst : nil
    }

    private func report(_ issue: XCUIAccessibilityAuditIssue, line: UInt) {
        let element = issue.element.map { "\($0.elementType.rawValue) '\($0.label)' id='\($0.identifier)' frame=\($0.frame)" } ?? "?"
        let path = NSTemporaryDirectory() + "audit-\(line)-\(UUID().uuidString.prefix(4)).png"
        try? XCUIScreen.main.screenshot().pngRepresentation.write(to: URL(fileURLWithPath: path))
        print("AUDIT ISSUE: \(issue.compactDescription) | \(issue.detailedDescription) | \(element) | \(path)")
    }
}

/// Frames the overlap rule needs, read once per audit pass.
struct Layout {
    let window: CGRect
    let covers: [CGRect]  // system bars and the keyboard
    let scrolls: [CGRect]
    let sheets: [CGRect]  // each presented sheet's real frame (`sheetContent()` in the app)

    @MainActor init(_ app: XCUIApplication) {
        window = app.windows.firstMatch.frame
        covers = [app.tabBars.firstMatch, app.navigationBars.firstMatch, app.keyboards.firstMatch].filter(\.exists).map(\.frame)
        scrolls = app.scrollViews.allElementsBoundByIndex.map(\.frame)
        sheets = app.descendants(matching: .any).matching(identifier: "sheet-root").allElementsBoundByIndex.map(\.frame)
    }

    /// The visible part of the innermost scroll view whose columns hold the frame: on iPad
    /// the screen behind a form sheet keeps its full-window scroll view in the tree, and a
    /// sheet stacked on a sheet reports a scroll view taller than the sheet shows.
    func innermostScroll(for frame: CGRect) -> CGRect? {
        func innermost(_ rects: [CGRect]) -> CGRect? {
            rects.filter { $0.minX <= frame.minX && $0.maxX >= frame.maxX }.min { $0.width * $0.height < $1.width * $1.height }
        }
        guard let scroll = innermost(scrolls) else { return nil }
        guard let sheet = innermost(sheets), sheet.intersects(scroll) else { return scroll }
        return scroll.intersection(sheet)
    }
}
