import SwiftUI

/// The event landing screen. Joining (QR, link, code) and search arrive in Phase 2; this
/// screen already shows the account state and any link the app was opened with.
struct HomeView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                HStack {
                    Text("EventFaces")
                        .font(.headline)
                        .foregroundStyle(Palette.text)
                    Spacer()
                    Button {
                        model.showSettings = true
                    } label: {
                        Image(systemName: "gearshape")
                            .font(.title3)
                            .foregroundStyle(Palette.text)
                            .frame(width: 44, height: 44)
                            .contentShape(.rect)
                    }
                    .accessibilityLabel("Settings")
                    .accessibilityIdentifier("open-settings")
                }
                if let notice = model.notice { noticeBanner(notice) }
                Text("Find your photos")
                    .font(.largeTitle.bold())
                    .foregroundStyle(Palette.text)
                    .accessibilityAddTraits(.isHeader)
                if let linkError = model.linkError { Banner(kind: .error, text: Text(linkError)).accessibilityIdentifier("link-error") }
                Text("Open your event's link or scan its QR code to get started.")
                    .foregroundStyle(Palette.textMuted)
                Button {
                    if case .signedIn = model.account { model.showJoin = true } else { model.showSignIn = true }
                } label: {
                    Label("Join an event", systemImage: "qrcode.viewfinder")
                }
                .buttonStyle(.primary)
                .accessibilityIdentifier("join-event")
                OrganizerSection()
                if !model.myEvents.isEmpty {
                    Text("My events").font(.headline).foregroundStyle(Palette.text).accessibilityAddTraits(.isHeader).padding(.top, 8)
                    ForEach(model.myEvents, id: \.id) { event in
                        Button { model.openEvent(event.id) } label: {
                            Card {
                                Text(event.name).font(.headline).foregroundStyle(Palette.text)
                                HStack {
                                    Text("\(event.photoCount ?? 0) photos").foregroundStyle(Palette.textMuted)
                                    Spacer()
                                    Text("Find my photos").foregroundStyle(Palette.accent)
                                    Image(systemName: "chevron.right").foregroundStyle(Palette.accent).accessibilityHidden(true)
                                }
                                .font(.subheadline)
                            }
                        }
                        .buttonStyle(.plain)
                        .accessibilityIdentifier("event-\(event.slug)")
                    }
                }
                if case .signedOut = model.account {
                    Button("Sign in") { model.showSignIn = true }
                        .buttonStyle(.primary)
                        .accessibilityIdentifier("home-sign-in")
                }
                if case let .signedIn(user) = model.account {
                    Card {
                        Text("Signed in as")
                            .font(.subheadline)
                            .foregroundStyle(Palette.textMuted)
                        Text(user.email)
                            .font(.headline)
                            .foregroundStyle(Palette.text)
                            .accessibilityIdentifier("signed-in-email")
                    }
                }
            }
            .padding(20)
            .readableWidth()
        }
        .background(Palette.bg.ignoresSafeArea())
        .navigationDestination(item: Binding(get: { model.organizerPath }, set: { model.organizerPath = $0 })) { route in
            OrganizerEventView(eventID: route.eventID)
        }
    }

    @ViewBuilder
    private func noticeBanner(_ notice: AppModel.Notice) -> some View {
        Group {
            switch notice {
            case .sessionEnded: Banner(kind: .info, text: Text("You were signed out. Sign in again to continue."))
            case .linkExpired: Banner(kind: .error, text: Text("This sign-in link has expired or was already used. Request a new code."))
            case .signedIn: Banner(kind: .success, text: Text("You're signed in."))
            case .accountDeleted: Banner(kind: .success, text: Text("Your account and its data were deleted."))
            }
        }
        .onTapGesture { model.dismissNotice() }
        .accessibilityAction(named: Text("Dismiss")) { model.dismissNotice() }  // the tap, for VoiceOver
        .accessibilityIdentifier("notice")
    }
}
