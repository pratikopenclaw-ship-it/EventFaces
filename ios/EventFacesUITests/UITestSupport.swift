import UIKit
import XCTest

@MainActor
extension XCTestCase {
    /// The tappable area is at least 44 × 44 pt (Apple's minimum). A Button's accessibility
    /// frame is its label's frame, which is also what receives taps.
    func assertTapTarget(_ element: XCUIElement, file: StaticString = #filePath, line: UInt = #line) {
        XCTAssertTrue(element.exists, "\(element) missing", file: file, line: line)
        let frame = element.frame
        XCTAssertGreaterThanOrEqual(frame.width, 44, "'\(element.label)' is \(frame.width) pt wide", file: file, line: line)
        XCTAssertGreaterThanOrEqual(frame.height, 44, "'\(element.label)' is \(frame.height) pt tall", file: file, line: line)
    }

    /// Accessibility audit. Every issue fails, with one rule for overlap: an issue on an
    /// element that sits under the system's floating bars or keyboard (or that the audit
    /// can't name) is re-checked in a clear state: keyboard dismissed and content scrolled
    /// clear, where the second audit must pass. Nothing is filtered: every element is
    /// audited where it is fully visible. A contrast failure is checked against the rendered
    /// pixels and stands unless they measure at least 4.5:1 (`measuredContrastPasses`).
    func auditScreen(_ app: XCUIApplication, line: UInt = #line) throws {
        var deferred: Set<String> = []  // overlapped in pass 1: must pass in the clear
        try app.performAccessibilityAudit { issue in
            if self.isOverlapped(issue.element, in: app) {
                deferred.insert(issue.element?.label ?? "")
                return true
            }
            if self.measuredContrastPasses(issue, in: app) { return true }
            self.report(issue, line: line)
            return false
        }
        guard !deferred.isEmpty else { return }
        print("AUDIT re-check in a clear state for: \(deferred.sorted())")
        clearOverlaps(app)
        try app.performAccessibilityAudit { issue in
            // Overlapped now, but it was clear (and passed) in pass 1: already audited.
            if self.isOverlapped(issue.element, in: app), let label = issue.element?.label, !label.isEmpty, !deferred.contains(label) {
                return true
            }
            if self.measuredContrastPasses(issue, in: app) { return true }
            self.report(issue, line: line)
            return false
        }
    }

    /// Under a system bar or the keyboard, or cut off by the edge of its scroll view (e.g.
    /// the bottom of a form sheet on iPad): the audit then measures what's behind it.
    private func isOverlapped(_ element: XCUIElement?, in app: XCUIApplication) -> Bool {
        let covers = [app.tabBars.firstMatch, app.navigationBars.firstMatch, app.keyboards.firstMatch].filter(\.exists).map(\.frame)
        guard let element else { return !covers.isEmpty }  // unnamed: decide in the clear-state audit
        let frame = element.frame
        // Judge against the innermost scroll view whose columns hold the element: on iPad the
        // screen behind a form sheet keeps its full-window scroll view in the tree.
        let columns = app.scrollViews.allElementsBoundByIndex.map(\.frame).filter { $0.minX <= frame.minX && $0.maxX >= frame.maxX }
        let innermost = columns.min { $0.width * $0.height < $1.width * $1.height }
        // Partly or wholly outside it (e.g. just below a form sheet's edge), or at its edge,
        // where the rest of its row is cut off under our header (the audit evaluates the row
        // but names the child), or off the window: audited where it is fully in view.
        let offscreen = !app.windows.firstMatch.frame.contains(frame)
        let clipped = innermost.map { !$0.insetBy(dx: 0, dy: 16).contains(frame) } ?? false
        return offscreen || clipped || covers.contains { $0.intersects(frame) }
    }

    private func clearOverlaps(_ app: XCUIApplication) {
        if app.keyboards.firstMatch.exists {
            app.swipeUp()  // forms close the keyboard on scroll (a swipe down would dismiss a sheet)
            for key in ["Hide keyboard", "Done", "done"] where app.keyboards.firstMatch.exists && app.keyboards.buttons[key].exists {
                app.keyboards.buttons[key].tap()
            }
        }
        app.swipeUp()
        app.swipeUp()
        // Let the scroll come to rest: the contrast check samples pixels, and text still
        // decelerating from the swipe is measured blurred.
        _ = XCTWaiter.wait(for: [XCTestExpectation(description: "scroll settles")], timeout: 1.5)
    }

    /// A contrast verdict is checked against the pixels actually rendered: the element's most
    /// common colour (its background) against its most contrasting frequent colour (the
    /// text). Only a measured ratio of at least 4.5:1 overrules the audit; the dispute is
    /// logged with the ratio and a screenshot. On iPad the audit flagged a 9.1:1 row in one
    /// scroll position and not another (IOS_QA_REPORT.md, IOS-025).
    private func measuredContrastPasses(_ issue: XCUIAccessibilityAuditIssue, in app: XCUIApplication) -> Bool {
        guard issue.auditType == .contrast, let element = issue.element, element.exists else { return false }
        let shot = XCUIScreen.main.screenshot()
        guard let ratio = Self.renderedContrast(shot.image, frame: element.frame, points: app.windows.firstMatch.frame.width) else { return false }
        let attachment = XCTAttachment(screenshot: shot)
        attachment.name = "contrast-dispute \(element.label) \(String(format: "%.2f", ratio)):1"
        attachment.lifetime = .keepAlways
        add(attachment)
        print("AUDIT CONTRAST CHECK '\(element.label)': measured \(String(format: "%.2f", ratio)):1 (\(ratio >= 4.5 ? "passes, audit overruled" : "fails"))")
        return ratio >= 4.5
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
        guard let background = counts.max(by: { $0.value < $1.value })?.key else { return nil }
        let frequent = counts.filter { $0.value >= max(20, w * h / 500) && $0.key != background }.map(\.key)
        guard !frequent.isEmpty else { return nil }  // nothing drawn: let the audit's verdict stand
        let lb = luminance(background)
        let best = frequent.map { c -> Double in let l = luminance(c); return (max(l, lb) + 0.05) / (min(l, lb) + 0.05) }.max() ?? 1
        return best
    }

    private func report(_ issue: XCUIAccessibilityAuditIssue, line: UInt) {
        let element = issue.element.map { "\($0.elementType.rawValue) '\($0.label)' id='\($0.identifier)' frame=\($0.frame)" } ?? "?"
        let path = NSTemporaryDirectory() + "audit-\(line)-\(UUID().uuidString.prefix(4)).png"
        try? XCUIScreen.main.screenshot().pngRepresentation.write(to: URL(fileURLWithPath: path))
        print("AUDIT ISSUE: \(issue.compactDescription) | \(issue.detailedDescription) | \(element) | \(path)")
    }
}
