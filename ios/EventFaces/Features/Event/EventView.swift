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

    enum Flow: Identifiable { case consent(ConsentInfo), capture; var id: String { switch self { case .consent: "consent"; case .capture: "capture" } } }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                if let error { Banner(kind: .error, text: Text(error)) }
                if let event {
                    if let logo {
                        Image(uiImage: logo).resizable().scaledToFit().frame(maxHeight: 56)
                            .accessibilityLabel(Text("\(event.name) logo"))
                    }
                    Text(event.name)
                        .font(.largeTitle.bold())
                        .foregroundStyle(Palette.text)
                        .accessibilityAddTraits(.isHeader)
                        .fixedSize(horizontal: false, vertical: true)
                    if let date = event.date.flatMap(Self.day) {
                        Text(date, format: .dateTime.day().month(.wide).year()).foregroundStyle(Palette.textMuted)
                    }
                    if !event.description.isEmpty {
                        Text(event.description).foregroundStyle(Palette.textMuted).fixedSize(horizontal: false, vertical: true)
                    }
                    if hasPhotos {
                        Button("My photos") { showResults = true }
                            .buttonStyle(.secondary)
                            .accessibilityIdentifier("my-photos")
                            .padding(.top, 8)
                    }
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
                } else if error == nil {
                    ProgressView().frame(maxWidth: .infinity, minHeight: 200)
                }
            }
            .padding(20)
            .readableWidth()
        }
        .background(Palette.bg.ignoresSafeArea())
        .task { await load() }
        .sheet(isPresented: $showUpload) { if let event { UploadView(event: event).hardScrollEdges() } }
        .onChange(of: model.openResultsFor) { _, id in if id == eventID { showResults = true; model.openResultsFor = nil } }
        .onAppear { if model.openResultsFor == eventID { showResults = true; model.openResultsFor = nil } }
        .fullScreenCover(isPresented: $showResults) {
            VStack(spacing: 0) {
                SheetHeader(title: "My photos", closeLabel: "Close") { showResults = false }
                ResultsView(eventID: eventID)
            }
            .background(Palette.bg.ignoresSafeArea())
            .environment(\.colorScheme, .dark)
            .hardScrollEdges()
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
            .hardScrollEdges()
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
