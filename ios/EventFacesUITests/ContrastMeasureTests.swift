import UIKit
import XCTest

/// The rendered-contrast check that can overrule the audit must never pass low contrast.
final class ContrastMeasureTests: XCTestCase {
    private func image(text: UIColor, on background: UIColor) -> UIImage {
        UIGraphicsImageRenderer(size: CGSize(width: 300, height: 60), format: {
            let f = UIGraphicsImageRendererFormat(); f.scale = 2; return f
        }()).image { _ in
            background.setFill()
            UIRectFill(CGRect(x: 0, y: 0, width: 300, height: 60))
            ("Delete my account" as NSString).draw(at: CGPoint(x: 16, y: 16), withAttributes: [.font: UIFont.systemFont(ofSize: 17), .foregroundColor: text])
        }
    }

    func testLowContrastTextMeasuresBelowTheBar() {
        // #777777 on #555555 is about 1.7:1.
        let ratio = XCTestCase.renderedContrast(image(text: UIColor(white: 0.467, alpha: 1), on: UIColor(white: 0.333, alpha: 1)),
                                                frame: CGRect(x: 0, y: 0, width: 300, height: 60), points: 300)
        XCTAssertLessThan(try XCTUnwrap(ratio), 4.5)
    }

    func testTheSettingsDangerRowMeasuresAboveTheBar() {
        // danger-text #FFA3A3 on surface #171A21 (dark): about 9:1.
        let ratio = XCTestCase.renderedContrast(
            image(text: UIColor(red: 1, green: 0.639, blue: 0.639, alpha: 1), on: UIColor(red: 0.090, green: 0.102, blue: 0.129, alpha: 1)),
            frame: CGRect(x: 0, y: 0, width: 300, height: 60), points: 300)
        XCTAssertGreaterThan(try XCTUnwrap(ratio), 7)
    }

    func testABrightIconCannotRescueDimText() {
        // Large dim text (#777 on #555) plus a small white mark: still measured as dim.
        let image = UIGraphicsImageRenderer(size: CGSize(width: 300, height: 60), format: {
            let f = UIGraphicsImageRendererFormat(); f.scale = 2; return f
        }()).image { _ in
            UIColor(white: 0.333, alpha: 1).setFill()
            UIRectFill(CGRect(x: 0, y: 0, width: 300, height: 60))
            UIColor.white.setFill()
            UIRectFill(CGRect(x: 280, y: 25, width: 6, height: 6))
            ("Delete my account and all my data" as NSString).draw(at: CGPoint(x: 16, y: 16), withAttributes: [.font: UIFont.systemFont(ofSize: 22), .foregroundColor: UIColor(white: 0.467, alpha: 1)])
        }
        let ratio = XCTestCase.renderedContrast(image, frame: CGRect(x: 0, y: 0, width: 300, height: 60), points: 300)
        XCTAssertLessThan(try XCTUnwrap(ratio), 4.5)
    }

    func testABrightTitleCannotRescueADimSubtitle() {
        let image = UIGraphicsImageRenderer(size: CGSize(width: 300, height: 80), format: {
            let f = UIGraphicsImageRendererFormat(); f.scale = 2; return f
        }()).image { _ in
            UIColor(white: 0.333, alpha: 1).setFill()
            UIRectFill(CGRect(x: 0, y: 0, width: 300, height: 80))
            ("Lock with Touch ID" as NSString).draw(at: CGPoint(x: 16, y: 8), withAttributes: [.font: UIFont.systemFont(ofSize: 20), .foregroundColor: UIColor.white])
            ("Asks when you come back" as NSString).draw(at: CGPoint(x: 16, y: 44), withAttributes: [.font: UIFont.systemFont(ofSize: 20), .foregroundColor: UIColor(white: 0.467, alpha: 1)])
        }
        let ratio = XCTestCase.renderedContrast(image, frame: CGRect(x: 0, y: 0, width: 300, height: 80), points: 300)
        XCTAssertLessThan(try XCTUnwrap(ratio), 4.5)
    }

    func testTextInItsOwnBoxIsMeasuredAgainstTheBox() {
        // A checkbox row: white text on a grey box with rounded corners on a darker page.
        let image = UIGraphicsImageRenderer(size: CGSize(width: 300, height: 80), format: {
            let f = UIGraphicsImageRendererFormat(); f.scale = 2; return f
        }()).image { _ in
            UIColor(white: 0.06, alpha: 1).setFill()
            UIRectFill(CGRect(x: 0, y: 0, width: 300, height: 80))
            UIColor(white: 0.12, alpha: 1).setFill()
            UIBezierPath(roundedRect: CGRect(x: 0, y: 0, width: 300, height: 80), cornerRadius: 10).fill()
            ("I accept the Terms of Use" as NSString).draw(at: CGPoint(x: 16, y: 24), withAttributes: [.font: UIFont.systemFont(ofSize: 22), .foregroundColor: UIColor.white])
        }
        let ratio = XCTestCase.renderedContrast(image, frame: CGRect(x: 0, y: 0, width: 300, height: 80), points: 300)
        XCTAssertGreaterThan(try XCTUnwrap(ratio), 10)
    }

    func testMutedParagraphTextUsesTheRealTokens() {
        // light text-muted #586B66 on light bg #F3F7F6 (about 5.4:1), several lines of body text.
        let image = UIGraphicsImageRenderer(size: CGSize(width: 300, height: 120), format: {
            let f = UIGraphicsImageRendererFormat(); f.scale = 2; return f
        }()).image { _ in
            UIColor(red: 0xF3 / 255, green: 0xF7 / 255, blue: 0xF6 / 255, alpha: 1).setFill()
            UIRectFill(CGRect(x: 0, y: 0, width: 300, height: 120))
            ("We are liable without limitation for intent and gross negligence, for injury to life, body or health, under the Product Liability Act." as NSString)
                .draw(in: CGRect(x: 12, y: 8, width: 276, height: 110), withAttributes: [.font: UIFont.systemFont(ofSize: 17), .foregroundColor: UIColor(red: 0x58 / 255, green: 0x6B / 255, blue: 0x66 / 255, alpha: 1)])
        }
        let ratio = try? XCTUnwrap(XCTestCase.renderedContrast(image, frame: CGRect(x: 0, y: 0, width: 300, height: 120), points: 300))
        XCTAssertNotNil(ratio)
        XCTAssertGreaterThan(ratio ?? 0, 4.5)
        XCTAssertLessThan(ratio ?? 99, 7)  // and not inflated
    }

    func testLargeTextInABoxOnAPage() {
        // The sign-in checkbox at the largest text size, dark: text on surface-2, box on the page.
        let image = UIGraphicsImageRenderer(size: CGSize(width: 300, height: 220), format: {
            let f = UIGraphicsImageRendererFormat(); f.scale = 2; return f
        }()).image { _ in
            UIColor(red: 0x0F / 255, green: 0x11 / 255, blue: 0x15 / 255, alpha: 1).setFill()
            UIRectFill(CGRect(x: 0, y: 0, width: 300, height: 220))
            UIColor(red: 0x1E / 255, green: 0x22 / 255, blue: 0x2B / 255, alpha: 1).setFill()
            UIBezierPath(roundedRect: CGRect(x: 0, y: 0, width: 300, height: 190), cornerRadius: 10).fill()
            ("I accept the Terms of Use and confirm" as NSString).draw(in: CGRect(x: 14, y: 12, width: 272, height: 170),
                withAttributes: [.font: UIFont.systemFont(ofSize: 40), .foregroundColor: UIColor(red: 0xF4 / 255, green: 0xF5 / 255, blue: 0xF7 / 255, alpha: 1)])
        }
        XCTAssertGreaterThan(try XCTUnwrap(XCTestCase.renderedContrast(image, frame: CGRect(x: 0, y: 0, width: 300, height: 220), points: 300)), 10)
    }

    func testADenseParagraphStillHasABackground() {
        // Small, tightly set text fills the frame: almost every background pixel is near a letter.
        let image = UIGraphicsImageRenderer(size: CGSize(width: 260, height: 70), format: {
            let f = UIGraphicsImageRendererFormat(); f.scale = 2; return f
        }()).image { _ in
            UIColor(red: 0x17 / 255, green: 0x1A / 255, blue: 0x21 / 255, alpha: 1).setFill()
            UIRectFill(CGRect(x: 0, y: 0, width: 260, height: 70))
            let style = NSMutableParagraphStyle(); style.lineSpacing = -2
            (String(repeating: "Wir sind nicht bereit und nicht verpflichtet ", count: 6) as NSString).draw(in: CGRect(x: 0, y: 0, width: 260, height: 70),
                withAttributes: [.font: UIFont.systemFont(ofSize: 12), .foregroundColor: UIColor(red: 0x9A / 255, green: 0xA1 / 255, blue: 0xAE / 255, alpha: 1), .paragraphStyle: style])
        }
        // dark text-muted #9AA1AE on surface #171A21: about 6.5:1.
        XCTAssertGreaterThan(try XCTUnwrap(XCTestCase.renderedContrast(image, frame: CGRect(x: 0, y: 0, width: 260, height: 70), points: 260)), 4.5)
    }

    func testABlankFrameMeasuresAsNothingDrawn() {
        // 1:1, "not drawn": the audit helper re-checks it scrolled into view, where it fails if still blank.
        XCTAssertEqual(XCTestCase.renderedContrast(image(text: .clear, on: .white), frame: CGRect(x: 0, y: 0, width: 300, height: 60), points: 300), 1)
    }
}
