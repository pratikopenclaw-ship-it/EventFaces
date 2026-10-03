import SwiftUI
import UIKit

/// Full-screen viewer: always dark, swipe between photos, pinch to zoom, landscape OK.
struct PhotoViewer: View {
    let results: ResultsModel
    let startIndex: Int
    @Environment(\.dismiss) private var dismiss
    @State private var index = 0
    @State private var reporting: MyPhoto?
    @State private var shareFile: URL?

    var body: some View {
        let photos = results.ordered
        ZStack {
            Color.black.ignoresSafeArea()
            if photos.isEmpty {
                Text("No photos").foregroundStyle(.white)
            } else {
                TabView(selection: $index) {
                    ForEach(Array(photos.enumerated()), id: \.element.id) { i, photo in
                        ZoomablePhoto(eventID: results.eventID, photoID: photo.id)
                            .tag(i)
                            .accessibilityLabel(Text("Photo \(i + 1) of \(photos.count)"))
                    }
                }
                .tabViewStyle(.page(indexDisplayMode: .never))
                .ignoresSafeArea()
                // On the pager only: on the container it would replace the identifiers of
                // every control inside (Close, verdicts, Save, Report).
                .accessibilityIdentifier("viewer")
            }
        }
        .safeAreaInset(edge: .top) { topBar(photos) }
        .safeAreaInset(edge: .bottom) { if photos.indices.contains(index) { bottomBar(photos[index]) } }
        .environment(\.colorScheme, .dark)
        .onAppear { index = min(startIndex, max(0, photos.count - 1)) }
        .onChange(of: photos.count) { _, count in if count == 0 { dismiss() } else { index = min(index, count - 1) } }
        .sheet(item: $reporting) { photo in ReportSheet(results: results, photo: photo).hardScrollEdges() }
        .sheet(item: Binding(get: { shareFile.map(SharedFile.init) }, set: { if $0 == nil { shareFile = nil } })) { file in
            ShareSheet(items: [file.url]) { try? FileManager.default.removeItem(at: file.url) }
        }
    }

    private func topBar(_ photos: [MyPhoto]) -> some View {
        HStack {
            Button("Close") { dismiss() }
                .foregroundStyle(.white)
                .buttonStyle(.tapTarget)
                .accessibilityIdentifier("viewer-close")
            Spacer()
            Text(verbatim: "\(min(index + 1, photos.count)) / \(photos.count)").foregroundStyle(.white.opacity(0.85)).monospacedDigit()
        }
        .padding(.horizontal, 16)
        .background(Color.black.opacity(0.6))
    }

    private func bottomBar(_ photo: MyPhoto) -> some View {
        VStack(spacing: 10) {
            if photo.tier != nil && photo.verdict != .me {
                HStack(spacing: 10) {
                    Button { Task { await results.verdict(photo, isMe: true) } } label: { Label("This is me", systemImage: "hand.thumbsup") }
                        .buttonStyle(.secondary)
                        .accessibilityIdentifier("verdict-me")
                    Button { Task { await results.verdict(photo, isMe: false) } } label: { Label("Not me", systemImage: "hand.thumbsdown") }
                        .buttonStyle(.secondary)
                        .accessibilityIdentifier("verdict-not-me")
                }
            }
            HStack(spacing: 10) {
                Button { Task { await results.save([photo.id]) } } label: { Label("Save", systemImage: "square.and.arrow.down") }
                    .buttonStyle(.secondary)
                    .accessibilityIdentifier("viewer-save")
                Button { Task { shareFile = await results.download([photo.id]) } } label: { Label("Share", systemImage: "square.and.arrow.up") }
                    .buttonStyle(.secondary)
                Button { reporting = photo } label: { Label("Report", systemImage: "flag") }
                    .buttonStyle(.secondary)
                    .accessibilityIdentifier("viewer-report")
            }
        }
        .labelStyle(.titleAndIcon)
        .padding(12)
        .background(Color.black.opacity(0.7))
    }
}

/// Pinch and double-tap zoom on the preview-size image (UIScrollView: native feel).
struct ZoomablePhoto: UIViewRepresentable {
    let eventID: String
    let photoID: String
    @Environment(AppModel.self) private var model

    func makeUIView(context: Context) -> UIScrollView {
        let scroll = UIScrollView()
        scroll.minimumZoomScale = 1
        scroll.maximumZoomScale = 4
        scroll.delegate = context.coordinator
        scroll.showsVerticalScrollIndicator = false
        scroll.showsHorizontalScrollIndicator = false
        let imageView = context.coordinator.imageView
        imageView.contentMode = .scaleAspectFit
        imageView.isAccessibilityElement = false
        scroll.addSubview(imageView)
        let tap = UITapGestureRecognizer(target: context.coordinator, action: #selector(Coordinator.doubleTap(_:)))
        tap.numberOfTapsRequired = 2
        scroll.addGestureRecognizer(tap)
        let events = model.events
        Task { @MainActor in
            imageView.image = try? await events.cachedImage(eventID: eventID, photoID: photoID, variant: "preview", maxPixel: 2400)
        }
        return scroll
    }

    func updateUIView(_ scroll: UIScrollView, context: Context) {
        context.coordinator.imageView.frame = scroll.bounds
    }

    func makeCoordinator() -> Coordinator { Coordinator() }

    final class Coordinator: NSObject, UIScrollViewDelegate {
        let imageView = UIImageView()
        func viewForZooming(in scrollView: UIScrollView) -> UIView? { imageView }
        @MainActor @objc func doubleTap(_ gesture: UITapGestureRecognizer) {
            guard let scroll = gesture.view as? UIScrollView else { return }
            scroll.setZoomScale(scroll.zoomScale > 1 ? 1 : 2.5, animated: !UIAccessibility.isReduceMotionEnabled)
        }
    }
}

/// Report a photo, including "it's me: remove it" (the removal request for your own photo).
struct ReportSheet: View {
    let results: ResultsModel
    let photo: MyPhoto
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var reason: ReportReason = .itsMeRemove
    @State private var details = ""
    @State private var state: State = .editing
    enum State { case editing, sending, sent, failed }

    var body: some View {
        VStack(spacing: 0) {
            SheetHeader(title: "Report photo") { dismiss() }
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    if state == .sent {
                        Banner(kind: .success, text: Text("Thanks. The organizer will review this photo."))
                    } else {
                        if state == .failed { Banner(kind: .error, text: Text("Couldn't send the report. Try again in a moment.")) }
                        Text("Why are you reporting this photo?").font(.headline).foregroundStyle(Palette.text)
                        ForEach([ReportReason.itsMeRemove, .privacy, .inappropriate, .other], id: \.self) { r in
                            Toggle(isOn: Binding(get: { reason == r }, set: { if $0 { reason = r } })) {
                                Text(label(r)).foregroundStyle(Palette.text)
                            }
                            .toggleStyle(CheckboxStyle())
                            .accessibilityAddTraits(.isButton)
                        }
                        TextField("Anything else the organizer should know (optional)", text: $details, axis: .vertical)
                            .lineLimit(3...6)
                            .padding(12)
                            .background(Palette.surface, in: .rect(cornerRadius: 12))
                            .overlay(RoundedRectangle(cornerRadius: 12).stroke(Palette.border))
                            .onChange(of: details) { _, v in details = String(v.prefix(1000)) }
                        Button("Send report") { Task { await send() } }
                            .buttonStyle(.primary)
                            .disabled(state == .sending)
                            .accessibilityIdentifier("send-report")
                    }
                }
                .padding(20)
            }
        }
        .background(Palette.bg.ignoresSafeArea())
    }

    private func label(_ r: ReportReason) -> LocalizedStringKey {
        switch r {
        case .itsMeRemove: "It's me and I want it removed"
        case .privacy: "It shows private information"
        case .inappropriate: "It's inappropriate"
        case .other: "Something else"
        }
    }

    private func send() async {
        state = .sending
        do {
            try await model.events.report(eventID: results.eventID, photoID: photo.id, reason: reason, details: details)
            state = .sent
        } catch {
            state = .failed
        }
    }
}

extension MyPhoto: Identifiable {}
