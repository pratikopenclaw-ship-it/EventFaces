import SwiftUI

/// Your photos for an event: best and possible matches, your uploads. Always dark.
struct ResultsView: View {
    let eventID: String
    @Environment(AppModel.self) private var model
    @State private var results: ResultsModel?
    @State private var viewerStart: ViewerStart?

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
                            LazyVGrid(columns: [GridItem(.adaptive(minimum: 104), spacing: 4)], spacing: 4) {
                                ForEach(items, id: \.id) { photo in
                                    tile(photo, results: results)
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
                Text(results.photos.isEmpty ? "No photos of you yet" : "We found you")
                    .font(.title2.bold()).foregroundStyle(Palette.text).accessibilityAddTraits(.isHeader)
                    .accessibilityIdentifier("results-title")
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
            // A square cell with the photo filling it, clipped: the photo can never spill
            // over its neighbours or the section headings.
            Color.clear
                .aspectRatio(1, contentMode: .fit)
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
