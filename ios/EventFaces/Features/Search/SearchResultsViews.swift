import SwiftUI

/// A busy server queued the search: we poll while this screen is open (the email and, from
/// Phase 4, a push notification cover the rest).
struct QueuedView: View {
    let eventID: String
    @Environment(AppModel.self) private var model
    @State private var status: SearchStatus?
    @State private var done = false

    var body: some View {
        Group {
            if done {
                ResultsView(eventID: eventID)
            } else {
                ScrollView {
                    VStack(alignment: .leading, spacing: 14) {
                        Image(systemName: "hourglass").font(.system(size: 40)).foregroundStyle(Palette.accent).accessibilityHidden(true)
                        Text("You're in the queue").font(.title2.bold()).foregroundStyle(Palette.text).accessibilityAddTraits(.isHeader)
                        Text("Lots of people are searching right now. We'll email you when your photos are ready, and show them here if this screen is still open.")
                            .foregroundStyle(Palette.textMuted).fixedSize(horizontal: false, vertical: true)
                        NotifyMeCard()
                        if status?.state == .rejected {
                            Banner(kind: .error, text: RejectionMessages.text(code: status?.code ?? "", serverMessage: status?.message ?? ""))
                        }
                        if [.expired, .cancelled].contains(status?.state) {
                            Banner(kind: .info, text: Text("This search didn't finish. Search again."))
                        }
                    }
                    .padding(20)
                    .readableWidth()
                }
                .accessibilityIdentifier("queued")
            }
        }
        .task { await poll() }
    }

    private func poll() async {
        while !Task.isCancelled {
            if let s = try? await model.events.searchStatus(eventID: eventID) {
                status = s
                if s.state == .done {
                    done = true
                    return
                }
                if [.rejected, .expired, .cancelled, .none].contains(s.state) { return }
            }
            try? await Task.sleep(for: .seconds(5))
        }
    }
}



/// Asked only here, when a search is queued: an explanation first, then the system prompt.
struct NotifyMeCard: View {
    @State private var state: State = .unknown
    enum State { case unknown, offer, on, declined }

    var body: some View {
        Group {
            switch state {
            case .offer:
                Card {
                    Label("Get a notification when your photos are ready", systemImage: "bell")
                        .font(.headline).foregroundStyle(Palette.text)
                    Text("We'll only notify you about your searches and your events. The notification never shows photos or names.")
                        .foregroundStyle(Palette.textMuted).fixedSize(horizontal: false, vertical: true)
                    Button("Notify me") {
                        Task { state = await PushManager.shared.requestAndRegister() ? .on : .declined }
                    }
                    .buttonStyle(.primary)
                    .accessibilityIdentifier("notify-me")
                }
            case .on:
                Banner(kind: .success, text: Text("We'll notify you when your photos are ready."))
            case .declined:
                Banner(kind: .info, text: Text("No notifications. We'll still email you."))
            case .unknown:
                EmptyView()
            }
        }
        .task { state = await PushManager.shared.isAuthorized ? .on : .offer }
    }
}
