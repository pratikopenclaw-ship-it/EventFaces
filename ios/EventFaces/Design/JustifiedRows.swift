import SwiftUI

/// Flex-wrap row packing with per-item aspect ratio (mirrors the web's `photo-gallery.tsx`
/// flexbox grid): each subview's natural width is `round(ratio * 190)`, rows that fill the
/// available width stretch their items in proportion to `ratio` to fill it exactly; the
/// last, incomplete row keeps its items at their natural width instead of stretching.
struct JustifiedRows: Layout {
    var spacing: CGFloat = 4

    struct AspectRatioKey: LayoutValueKey {
        static let defaultValue: CGFloat = 4.0 / 3.0
    }

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let width = proposal.width ?? 0
        let rows = pack(subviews: subviews, width: width)
        let height = rows.reduce(0) { $0 + $1.height } + spacing * CGFloat(max(0, rows.count - 1))
        return CGSize(width: width, height: height)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        let rows = pack(subviews: subviews, width: bounds.width)
        var y = bounds.minY
        for row in rows {
            var x = bounds.minX
            for item in row.items {
                subviews[item.index].place(at: CGPoint(x: x, y: y), anchor: .topLeading, proposal: ProposedViewSize(width: item.width, height: item.width / item.ratio))
                x += item.width + spacing
            }
            y += row.height + spacing
        }
    }

    // MARK: - Packing

    private struct Item { let index: Int; let ratio: CGFloat; let basis: CGFloat; var width: CGFloat }
    private struct Row { var items: [Item]; let height: CGFloat }

    private func pack(subviews: Subviews, width: CGFloat) -> [Row] {
        guard width > 0, !subviews.isEmpty else { return [] }
        let items = subviews.indices.map { i in
            let ratio = max(0.5, min(2.5, subviews[i][AspectRatioKey.self]))
            return (index: i, ratio: ratio, basis: (ratio * 190).rounded())
        }

        var rows: [[(index: Int, ratio: CGFloat, basis: CGFloat)]] = [[]]
        var rowWidth: CGFloat = 0
        for item in items {
            let needed = rowWidth == 0 ? item.basis : rowWidth + spacing + item.basis
            if needed > width, !rows[rows.count - 1].isEmpty {
                rows.append([item])
                rowWidth = item.basis
            } else {
                rows[rows.count - 1].append(item)
                rowWidth = needed
            }
        }

        return rows.enumerated().map { rowIndex, rowItems in
            let isLastRow = rowIndex == rows.count - 1
            let gaps = spacing * CGFloat(max(0, rowItems.count - 1))
            let basisSum = rowItems.reduce(0 as CGFloat) { $0 + $1.basis }
            let extra = max(0, width - basisSum - gaps)
            let ratioSum = rowItems.reduce(0 as CGFloat) { $0 + $1.ratio }
            // The web's last row keeps a flex-grow(10) spacer that absorbs the leftover
            // space, so its real tiles stay at their natural (unstretched) width.
            let stretched = (isLastRow || ratioSum == 0)
                ? rowItems.map { Item(index: $0.index, ratio: $0.ratio, basis: $0.basis, width: $0.basis) }
                : rowItems.map { Item(index: $0.index, ratio: $0.ratio, basis: $0.basis, width: $0.basis + extra * ($0.ratio / ratioSum)) }
            let height = stretched.map { $0.width / $0.ratio }.max() ?? 0
            return Row(items: stretched, height: height)
        }
    }
}

extension View {
    /// Declares this view's aspect ratio to an enclosing `JustifiedRows` layout.
    func justifiedAspectRatio(_ ratio: CGFloat) -> some View {
        layoutValue(key: JustifiedRows.AspectRatioKey.self, value: ratio)
    }
}
