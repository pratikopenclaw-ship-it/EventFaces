import SwiftUI
import WebKit

/// Organizer-added video links, shown as a tappable list; read-only (management stays on
/// the web). Tapping opens the provider's embed in a full-screen sheet.
struct VideosSection: View {
    let videos: [EventVideo]
    @State private var playing: PlayingVideo?

    private struct PlayingVideo: Identifiable {
        let video: EventVideo
        var id: String { video.id }
    }

    var body: some View {
        if !videos.isEmpty {
            VStack(alignment: .leading, spacing: 8) {
                Text("Videos").font(.headline).foregroundStyle(Palette.text).accessibilityAddTraits(.isHeader)
                VStack(spacing: 1) {
                    ForEach(videos, id: \.id) { video in
                        Button { playing = PlayingVideo(video: video) } label: {
                            HStack(spacing: 10) {
                                Image(systemName: "play.circle.fill").foregroundStyle(Palette.textMuted)
                                Text(video.title).foregroundStyle(Palette.text).lineLimit(1)
                                Spacer()
                            }
                            .padding(12)
                            .background(Palette.surface)
                            .contentShape(.rect)
                        }
                        .buttonStyle(.plain)
                        .accessibilityIdentifier("video-\(video.id)")
                        .accessibilityHint(Text("Plays the video"))
                    }
                }
                .clipShape(.rect(cornerRadius: 12))
            }
            .accessibilityIdentifier("videos")
            .fullScreenCover(item: $playing) { playing in
                VStack(spacing: 0) {
                    SheetHeader(title: LocalizedStringKey(playing.video.title), closeLabel: "Close") { self.playing = nil }
                    VideoEmbedView(url: playing.video.embedUrl)
                }
                .background(Palette.bg.ignoresSafeArea())
                .sheetContent()
            }
        }
    }
}

/// A provider's embed page in a non-persistent WebView: no cookies or cache survive past
/// this sheet, matching the app's "never persist more than necessary" stance elsewhere.
struct VideoEmbedView: UIViewRepresentable {
    let url: String

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .nonPersistent()
        config.allowsInlineMediaPlayback = true
        let view = WKWebView(frame: .zero, configuration: config)
        view.accessibilityIdentifier = "video-embed"
        return view
    }

    func updateUIView(_ view: WKWebView, context: Context) {
        guard let target = URL(string: url) else { return }
        if view.url != target { view.load(URLRequest(url: target)) }
    }
}
