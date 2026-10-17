import SwiftUI

/// An event's landing screen: organizer logo and accent, then "Find my photos".
struct EventView: View {
    let eventID: String
    @Environment(AppModel.self) private var model
    @State private var event: EventDetail?
    @State private var error: LocalizedStringKey?
    @State private var logo: UIImage?
    @State private var flow: Flow?
    @State private var hasPhotos = false
    @State private var showResults = false
    @State private var showUpload = false
    @State private var stats: OrganizerStats?
    @State private var videos: [EventVideo] = []

    enum Flow: Identifiable { case consent(ConsentInfo), capture; var id: String { switch self { case .consent: "consent"; case .capture: "capture" } } }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                if let error { Banner(kind: .error, text: Text(error)) }
                if let event {
                    cover(event)
                    if !event.description.isEmpty {
                        Text(event.description).foregroundStyle(Palette.textMuted).fixedSize(horizontal: false, vertical: true)
                    }
                    if hasPhotos {
                        Button("My photos") { showResults = true }
                            .buttonStyle(.secondary)
                            .accessibilityIdentifier("my-photos")
                            .padding(.top, 8)
                    }
                    VideosSection(videos: videos)
                        .padding(.top, 8)
                    if event.guestUploadEnabled {
                        Button { showUpload = true } label: { Label("Add your photos", systemImage: "square.and.arrow.up.on.square") }
                            .buttonStyle(.secondary)
                            .accessibilityIdentifier("add-photos")
                            .padding(.top, 8)
                    }
                    Button(hasPhotos ? "Search again" : "Find my photos") { Task { await findMyPhotos() } }
                        .buttonStyle(AccentButtonStyle(accent: EventAccent.color(event.accentColor), onAccent: EventAccent.onColor(event.accentColor)))
                        .accessibilityIdentifier("find-my-photos")
                        .padding(.top, 8)
                    if model.myEvents.first(where: { $0.id == eventID })?.canManage == true {
                        OrganizerStatsSection(stats: stats)
                            .padding(.top, 16)
                    }
                } else if error == nil {
                    ProgressView().frame(maxWidth: .infinity, minHeight: 200)
                }
            }
            .padding(20)
            .readableWidth()
        }
        .background(Palette.bg.ignoresSafeArea())
        .task { await load() }
        .sheet(isPresented: $showUpload) { if let event { UploadView(event: event).sheetContent() } }
        .onChange(of: model.openResultsFor) { _, id in if id == eventID { showResults = true; model.openResultsFor = nil } }
        .onAppear { if model.openResultsFor == eventID { showResults = true; model.openResultsFor = nil } }
        .fullScreenCover(isPresented: $showResults) {
            VStack(spacing: 0) {
                SheetHeader(title: "My photos", closeLabel: "Close") { showResults = false }
                ResultsView(eventID: eventID)
            }
            .background(Palette.bg.ignoresSafeArea())
            .environment(\.colorScheme, .dark)
            .sheetContent()
        }
        .fullScreenCover(item: $flow) { flow in
            Group {
                switch flow {
                case let .consent(info):
                    ConsentView(info: info) { self.flow = .capture } onCancel: { self.flow = nil }
                case .capture:
                    CaptureView(eventID: eventID) {
                        self.flow = nil
                        Task { hasPhotos = !((try? await model.events.photos(eventID: eventID)) ?? []).isEmpty }
                    }
                }
            }
            .sheetContent()
        }
    }

    /// Event dates are calendar days ("2026-10-01"), shown in the user's locale.
    static func day(_ s: String) -> Date? {
        try? Date(s, strategy: .iso8601.year().month().day())
    }

    private func load() async {
        do {
            let e = try await model.events.event(eventID)
            event = e
            hasPhotos = !((try? await model.events.photos(eventID: eventID)) ?? []).isEmpty
            if e.hasLogo == true, let data = try? await model.events.image(path: "/api/events/\(eventID)/logo") { logo = UIImage(data: data) }
            videos = (try? await model.events.videos(eventID: eventID)) ?? []
            if model.myEvents.first(where: { $0.id == eventID })?.canManage == true {
                stats = await model.events.organizerStats(eventID)
            }
        } catch AppError.noAccess {
            error = "You don't have access to this event (any more)."
        } catch {
            self.error = "Couldn't load this event. Check your connection and try again."
        }
    }

    private func findMyPhotos() async {
        do {
            let consent = try await model.events.consent()
            flow = consent.given ? .capture : .consent(consent)
        } catch {
            self.error = "Couldn't load this event. Check your connection and try again."
        }
    }

    /// The accent band with the seeded tile pattern, the organizer's logo and the event's
    /// name/date on solid accent below it (never over the pattern, for contrast).
    @ViewBuilder
    private func cover(_ event: EventDetail) -> some View {
        let accent = EventAccent.color(event.accentColor) ?? Palette.accent
        let onAccent = EventAccent.onColor(event.accentColor) ?? Palette.onAccent
        VStack(alignment: .leading, spacing: 0) {
            CoverPattern(seed: eventID, rows: 3, tint: onAccent).frame(height: 112)
            VStack(alignment: .leading, spacing: 6) {
                if let logo {
                    Image(uiImage: logo).resizable().scaledToFit().frame(maxHeight: 40)
                        .accessibilityLabel(Text("\(event.name) logo"))
                }
                Text(event.name)
                    .font(.largeTitle.bold())
                    .foregroundStyle(onAccent)
                    .accessibilityAddTraits(.isHeader)
                    .fixedSize(horizontal: false, vertical: true)
                if let date = event.date.flatMap(Self.day) {
                    Text(date, format: .dateTime.day().month(.wide).year()).foregroundStyle(onAccent.opacity(0.85))
                }
            }
            .padding(16)
        }
        .background(accent)
        .clipShape(.rect(cornerRadius: 24))
    }
}

/// At-a-glance numbers for organizers (read-only; management stays on the web): the same
/// four tiles as the web dashboard. Each tile shows "—" if its own fetch failed.
struct OrganizerStatsSection: View {
    let stats: OrganizerStats?

    private let columns = [GridItem(.flexible()), GridItem(.flexible())]

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("For organizers").font(.subheadline.weight(.semibold)).foregroundStyle(Palette.textMuted)
            LazyVGrid(columns: columns, spacing: 12) {
                tile(label: "Photos", value: stats?.publishedPhotos,
                     description: stats?.facesFound.map { "\($0) faces found" })
                tile(label: "Members", value: stats?.approvedMembers,
                     description: (stats?.pendingMembers).flatMap { $0 > 0 ? "\($0) pending" : nil })
                tile(label: "Searches", value: stats?.searchCount,
                     description: stats?.matchRatePercent.map { "\($0)% found a match" })
                tile(label: "Needs attention", value: stats?.needsAttention,
                     description: (stats?.needsAttention == 0) ? "All clear" : nil,
                     tone: stats?.needsAttention.map { $0 > 0 ? .warn : .good } ?? .neutral)
            }
        }
        .accessibilityIdentifier("organizer-stats")
    }

    private enum Tone { case neutral, good, warn }

    @ViewBuilder
    private func tile(label: String, value: Int?, description: String?, tone: Tone = .neutral) -> some View {
        let valueColor: Color = switch tone {
        case .neutral: Palette.text
        case .good: Palette.successText
        case .warn: Palette.warningText
        }
        VStack(alignment: .leading, spacing: 2) {
            Text(label).font(.caption).foregroundStyle(Palette.textMuted)
            Text(value.map(String.init) ?? "—").font(.title2.weight(.semibold)).foregroundStyle(valueColor)
            if let description { Text(description).font(.caption2).foregroundStyle(Palette.textMuted) }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .background(Palette.surface, in: .rect(cornerRadius: 12))
        .accessibilityElement(children: .combine)
    }
}

/// Primary style in the event's accent (readable in both themes), or the app accent.
struct AccentButtonStyle: ButtonStyle {
    let accent: Color?
    let onAccent: Color?
    @Environment(\.isEnabled) private var isEnabled

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.body.weight(.semibold))
            .frame(maxWidth: .infinity, minHeight: 50)
            .foregroundStyle(isEnabled ? (onAccent ?? Palette.onAccent) : Palette.textMuted)
            .background(isEnabled ? (accent ?? Palette.accent) : Palette.surface2, in: .rect(cornerRadius: 12))
            .opacity(configuration.isPressed ? 0.85 : 1)
    }
}
