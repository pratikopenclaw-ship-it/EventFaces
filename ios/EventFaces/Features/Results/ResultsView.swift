import SwiftUI

/// Your photos for an event: best and possible matches, your uploads. Always dark.
struct ResultsView: View {
    let eventID: String
    @Environment(AppModel.self) private var model
    @State private var results: ResultsModel?
    @State private var viewerStart: ViewerStart?
    @State private var revealed = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    struct ViewerStart: Identifiable { let index: Int; var id: Int { index } }

    var body: some View {
        Group {
            if let results { content(results) } else { ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity) }
        }
        .background(Palette.bg.ignoresSafeArea())
        .environment(\.colorScheme, .dark)  // photos always display on a dark background
        .onAppear {
            if results == nil { results = ResultsModel(eventID: eventID, service: model.events, session: model.auth.session, config: model.config) }
        }
        .task(id: results == nil) { await results?.load() }
    }

    @ViewBuilder
    private func content(_ results: ResultsModel) -> some View {
        @Bindable var results = results
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                header(results)
                if let message = results.message { banner(message).onTapGesture { results.dismissMessage() } }
                if results.noAccess {
                    Banner(kind: .error, text: Text("You don't have access to this event (any more). Its photos were removed from this device."))
                        .accessibilityIdentifier("results-no-access")
                } else if !results.loading && results.photos.isEmpty {
                    Text("New photos may still be added. Try again later.").foregroundStyle(Palette.textMuted)
                }
                ForEach(ResultsModel.Section.allCases) { section in
                    let items = results.photos(in: section)
                    if !items.isEmpty {
                        VStack(alignment: .leading, spacing: 8) {
                            Text(title(section)).font(.headline).foregroundStyle(Palette.text).accessibilityAddTraits(.isHeader)
                            if section == .possible {
                                Text("Less certain. Tell us if these are you.").font(.footnote).foregroundStyle(Palette.textMuted)
                            }
                            // Justified rows: nothing is cropped to a square, each row fills the width.
                            JustifiedRows(rowHeight: 120, spacing: 4) {
                                ForEach(Array(items.enumerated()), id: \.element.id) { i, photo in
                                    tile(photo, results: results)
                                        .layoutValue(key: AspectRatio.self, value: Self.ratio(photo))
                                        .modifier(Reveal(index: i, shown: revealed || reduceMotion))
                                }
                            }
                        }
                    }
                }
                if !results.noAccess {
                    Button("Photos of me are missing") { Task { await results.reportMissing() } }
                        .buttonStyle(.secondary)
                        .accessibilityIdentifier("missing")
                }
            }
            .padding(16)
            .padding(.bottom, results.selecting ? 90 : 0)
        }
        // On the scroll view itself: after .safeAreaInset it would also replace the action
        // bar's identifiers.
        .accessibilityIdentifier("results")
        .refreshable { await results.load() }
        // The photos appear once, as a short cascade (skipped with Reduce Motion).
        .onChange(of: results.loading, initial: true) { _, loading in if !loading { revealed = true } }
        .safeAreaInset(edge: .bottom) {
            if results.selecting { actionBar(results) }
        }
        .fullScreenCover(item: $viewerStart) { start in
            PhotoViewer(results: results, startIndex: start.index)
        }
        .sheet(item: Binding(get: { results.shareFile.map(SharedFile.init) }, set: { if $0 == nil { results.shareFile = nil } })) { file in
            ShareSheet(items: [file.url]) {
                try? FileManager.default.removeItem(at: file.url)  // nothing stays behind after sharing
            }
        }
    }

    private func header(_ results: ResultsModel) -> some View {
        HStack(alignment: .firstTextBaseline) {
            VStack(alignment: .leading, spacing: 4) {
                headline(results)
                    .font(.title2.bold()).foregroundStyle(Palette.text).accessibilityAddTraits(.isHeader)
                    .accessibilityIdentifier("results-title")
                    .fixedSize(horizontal: false, vertical: true)
                if !results.photos.isEmpty {
                    Text("\(results.photos.count) photos").foregroundStyle(Palette.textMuted)
                }
            }
            Spacer()
            if !results.photos.isEmpty {
                Button(results.selecting ? "Done" : "Select") {
                    results.selecting.toggle()
                    if !results.selecting { results.selected = [] }
                }
                .foregroundStyle(Palette.text)
                .buttonStyle(.tapTarget)
                .accessibilityIdentifier("select")
            }
        }
    }

    private func tile(_ photo: MyPhoto, results: ResultsModel) -> some View {
        let isSelected = results.selected.contains(photo.id)
        return Button {
            if results.selecting { results.toggle(photo.id) } else if let i = results.ordered.firstIndex(where: { $0.id == photo.id }) { viewerStart = ViewerStart(index: i) }
        } label: {
            // The cell takes the photo's shape (from its row); the photo fills it, clipped, so
            // it can never spill over its neighbours or the section headings.
            Color.clear
                .overlay { CachedPhoto(eventID: eventID, photoID: photo.id, variant: "thumb", maxPixel: 360) }
                .clipped()
                .overlay(alignment: .topLeading) {
                    if results.selecting {
                        Image(systemName: isSelected ? "checkmark.circle.fill" : "circle")
                            .font(.title3)
                            .foregroundStyle(isSelected ? Palette.accent : .white)
                            .shadow(radius: 2)
                            .padding(6)
                    }
                }
                .overlay(alignment: .bottomTrailing) {
                    if photo.verdict == .me {
                        Image(systemName: "person.fill.checkmark").foregroundStyle(.white).padding(6).shadow(radius: 2)
                    }
                }
                .clipShape(.rect(cornerRadius: 6))
                // Color.clear isn't hit-testable: without this a tile whose thumbnail is
                // still loading ignores taps.
                .contentShape(.rect(cornerRadius: 6))
        }
        .buttonStyle(.plain)
        .accessibilityLabel(Text(photo.verdict == .me ? "Photo, marked as you" : "Photo"))
        .accessibilityAddTraits(isSelected ? [.isSelected] : [])
        .accessibilityHint(results.selecting ? Text("Selects the photo") : Text("Opens the photo"))
        .accessibilityIdentifier("photo-\(photo.id)")
    }

    private func actionBar(_ results: ResultsModel) -> some View {
        HStack(spacing: 10) {
            Button { Task { await results.save(Array(results.selected)) } } label: { Label("Save", systemImage: "square.and.arrow.down") }
                .buttonStyle(.secondary)
                .accessibilityIdentifier("save-selected")
            Button { Task { await results.shareSelection() } } label: { Label("Share", systemImage: "square.and.arrow.up") }
                .buttonStyle(.secondary)
            Button { Task { await results.downloadAll() } } label: { Label("All (ZIP)", systemImage: "archivebox") }
                .buttonStyle(.primary)
                .accessibilityIdentifier("download-all")
        }
        .disabled(results.busy)
        .labelStyle(.titleAndIcon)
        .padding(12)
        .background(Palette.surface.ignoresSafeArea(edges: .bottom))
        .overlay(alignment: .top) { Divider().overlay(Palette.border) }
    }

    /// "You're in N photos": matches only, like the web (own uploads aren't a match).
    private func headline(_ results: ResultsModel) -> Text {
        let matches = results.photos.filter { $0.tier != nil }.count
        if results.photos.isEmpty { return Text("No photos of you yet") }
        return matches > 0 ? Text("You're in \(matches) photos") : Text("Your photos")
    }

    /// Width / height, clamped like the web's gallery so panoramas and strips stay usable.
    static func ratio(_ photo: MyPhoto) -> CGFloat {
        guard let w = photo.width, let h = photo.height, w > 0, h > 0 else { return 4.0 / 3.0 }
        return min(2.5, max(0.5, CGFloat(w) / CGFloat(h)))
    }

    private func title(_ section: ResultsModel.Section) -> LocalizedStringKey {
        switch section {
        case .best: "Best matches"
        case .possible: "Possible matches"
        case .uploads: "Your uploads"
        }
    }

    private func banner(_ message: ResultsModel.Message) -> Banner {
        switch message {
        case .missingReported: Banner(kind: .success, text: Text("Thanks. We've told the organizer some of your photos may be missing."))
        case .saved: Banner(kind: .success, text: Text("Saved to Photos."))
        case .downloadFailed: Banner(kind: .error, text: Text("The download didn't finish. Check your connection and try again."))
        case .saveFailed: Banner(kind: .error, text: Text("Couldn't save to Photos. Allow EventFaces to add photos in Settings."))
        case .expired: Banner(kind: .error, text: Text("This download link has expired. Try again."))
        case .failed: Banner(kind: .error, text: Text("Something went wrong on our side. Try again in a moment."))
        }
    }
}

struct SharedFile: Identifiable { let url: URL; var id: String { url.path } }

/// A photo from the protected cache (downsampled to `maxPixel`), fetched once if missing.
struct CachedPhoto: View {
    let eventID: String
    let photoID: String
    let variant: String
    let maxPixel: CGFloat
    @Environment(AppModel.self) private var model
    @State private var image: UIImage?

    var body: some View {
        ZStack {
            Palette.surface2
            if let image { Image(uiImage: image).resizable().scaledToFill() }
        }
        .task(id: photoID + variant) {
            image = try? await model.events.cachedImage(eventID: eventID, photoID: photoID, variant: variant, maxPixel: maxPixel)
        }
    }
}

/// The system share sheet (Save to Files, AirDrop, …).
struct ShareSheet: UIViewControllerRepresentable {
    let items: [Any]
    let onFinish: () -> Void

    func makeUIViewController(context: Context) -> UIActivityViewController {
        let vc = UIActivityViewController(activityItems: items, applicationActivities: nil)
        vc.completionWithItemsHandler = { _, _, _, _ in onFinish() }
        return vc
    }

    func updateUIViewController(_ vc: UIActivityViewController, context: Context) {}
}

/// A photo's aspect ratio for `JustifiedRows`.
struct AspectRatio: LayoutValueKey { static let defaultValue: CGFloat = 1 }

/// Rows of photos at their own aspect ratio: fill each row to the width (like the web's
/// gallery), the last row keeps the target height instead of stretching.
struct JustifiedRows: Layout {
    let rowHeight: CGFloat
    let spacing: CGFloat

    struct Row { var indices: [Int]; var height: CGFloat }

    static func rows(ratios: [CGFloat], width: CGFloat, rowHeight: CGFloat, spacing: CGFloat) -> [Row] {
        guard width > 0 else { return [] }
        var rows: [Row] = []
        var current: [Int] = []
        var sum: CGFloat = 0
        for (i, r) in ratios.enumerated() {
            current.append(i)
            sum += r
            let natural = sum * rowHeight + CGFloat(current.count - 1) * spacing
            if natural >= width {
                // Scale the row so it fills the width exactly.
                let h = (width - CGFloat(current.count - 1) * spacing) / sum
                rows.append(Row(indices: current, height: h))
                current = []
                sum = 0
            }
        }
        if !current.isEmpty {
            let fit = (width - CGFloat(current.count - 1) * spacing) / sum
            rows.append(Row(indices: current, height: min(rowHeight, fit)))
        }
        return rows
    }

    private func layout(_ subviews: Subviews, width: CGFloat) -> [Row] {
        Self.rows(ratios: subviews.map { $0[AspectRatio.self] }, width: width, rowHeight: rowHeight, spacing: spacing)
    }

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let width = proposal.width ?? 360
        let rows = layout(subviews, width: width)
        let height = rows.reduce(0) { $0 + $1.height } + CGFloat(max(0, rows.count - 1)) * spacing
        return CGSize(width: width, height: height)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var y = bounds.minY
        for row in layout(subviews, width: bounds.width) {
            var x = bounds.minX
            for i in row.indices {
                let w = subviews[i][AspectRatio.self] * row.height
                subviews[i].place(at: CGPoint(x: x, y: y), proposal: ProposedViewSize(width: w, height: row.height))
                x += w + spacing
            }
            y += row.height + spacing
        }
    }
}

/// Fade-and-rise in a short cascade the first time results show.
struct Reveal: ViewModifier {
    let index: Int
    let shown: Bool

    func body(content: Content) -> some View {
        content
            .opacity(shown ? 1 : 0)
            .offset(y: shown ? 0 : 12)
            .animation(.easeOut(duration: 0.35).delay(Double(min(index, 14)) * 0.04), value: shown)
    }
}
