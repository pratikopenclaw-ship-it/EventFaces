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

    func testABlankElementLeavesTheVerdictToTheAudit() {
        XCTAssertNil(XCTestCase.renderedContrast(image(text: .clear, on: .white), frame: CGRect(x: 0, y: 0, width: 300, height: 60), points: 300))
    }
}
