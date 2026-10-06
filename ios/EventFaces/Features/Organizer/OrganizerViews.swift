import SwiftUI

/// The events this user manages (organizers and super admins).
struct OrganizerSection: View {
    @Environment(AppModel.self) private var model
    var body: some View {
        let managed = model.myEvents.filter { $0.canManage == true }
        if !managed.isEmpty {
            VStack(alignment: .leading, spacing: 8) {
                Text("Events you organize").font(.headline).foregroundStyle(Palette.text).accessibilityAddTraits(.isHeader)
                ForEach(managed, id: \.id) { event in
                    NavigationLink(value: OrganizerRoute(eventID: event.id)) {
                        Card {
                            Text(event.name).font(.headline).foregroundStyle(Palette.text)
                            HStack {
                                Text("\(event.photoCount ?? 0) photos").foregroundStyle(Palette.textMuted)
                                Spacer()
                                Text("Manage").foregroundStyle(Palette.accent)
                                Image(systemName: "chevron.right").foregroundStyle(Palette.accent).accessibilityHidden(true)
                            }
                            .font(.subheadline)
                        }
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("manage-\(event.slug)")
                }
            }
            .padding(.top, 8)
        }
    }
}

struct OrganizerRoute: Hashable { let eventID: String }

struct OrganizerEventView: View {
    let eventID: String
    @Environment(AppModel.self) private var model
    @State private var tab: Tab = .share
    enum Tab: String, CaseIterable { case share, moderation, members }

    var body: some View {
        VStack(spacing: 0) {
            Picker("Section", selection: $tab) {
                Text("Share").tag(Tab.share)
                Text("Review").tag(Tab.moderation)
                Text("Members").tag(Tab.members)
            }
            .pickerStyle(.segmented)
            .padding(16)
            .accessibilityIdentifier("organizer-tabs")
            switch tab {
            case .share: OrganizerShare(eventID: eventID)
            case .moderation: ModerationQueue(eventID: eventID)
            case .members: MembersList(eventID: eventID)
            }
        }
        .background(Palette.bg.ignoresSafeArea())
        .navigationBarTitleDisplayMode(.inline)
    }
}

/// QR code and join link to show or share; sync status and photo counts.
private struct OrganizerShare: View {
    let eventID: String
    @Environment(AppModel.self) private var model
    @State private var admin: EventAdmin?
    @State private var sync: SyncStatusInfo?
    @State private var qr: UIImage?
    @State private var error = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                if error { Banner(kind: .error, text: Text("You don't have access to this event (any more).")) }
                if let admin {
                    EventCover(name: admin.name, seed: admin.id, accentHex: admin.accentColor)
                    if admin.joinMode == .code {
                        if let qr {
                            Image(uiImage: qr).interpolation(.none).resizable().scaledToFit()
                                .frame(maxWidth: 240).padding(12).background(.white, in: .rect(cornerRadius: 12))
                                .frame(maxWidth: .infinity)
                                .accessibilityLabel("QR code to join \(admin.name)")
                        }
                        ValueRowView(title: "Access code", value: admin.accessCode)
                        if let link = joinLink(admin) {
                            ShareLink(item: link) { Label("Share join link", systemImage: "square.and.arrow.up") }
                                .buttonStyle(.primary)
                                .accessibilityIdentifier("share-join-link")
                        }
                    } else {
                        Text("This event is invite-only: invite people from the web dashboard.").foregroundStyle(Palette.textMuted)
                    }
                }
                if let sync {
                    Card {
                        Text("Photos").font(.headline).foregroundStyle(Palette.text)
                        Text("\(sync.publishedPhotos) published · \(sync.faces) faces indexed").foregroundStyle(Palette.textMuted)
                        Text(sync.inProgress ? String(localized: "Importing from Google Drive…") : (sync.driveConfigured ? String(localized: "Drive import is set up.") : String(localized: "Drive import isn't set up (web dashboard).")))
                            .font(.footnote).foregroundStyle(Palette.textMuted)
                    }
                }
            }
            .padding(16)
            .readableWidth()
        }
        .task {
            do {
                admin = try await model.events.admin(eventID)
                sync = try? await model.events.syncStatus(eventID)
                if admin?.joinMode == .code, let data = try? await model.events.image(path: "/api/events/\(eventID)/qr?format=png") { qr = UIImage(data: data) }
            } catch { self.error = true }
        }
    }

    private func joinLink(_ admin: EventAdmin) -> URL? {
        var parts = URLComponents(url: model.config.apiBaseURL, resolvingAgainstBaseURL: false)
        parts?.path = "/join/\(admin.slug)"
        parts?.queryItems = [URLQueryItem(name: "code", value: admin.accessCode)]
        return parts?.url
    }
}

/// Guest uploads waiting for approval.
private struct ModerationQueue: View {
    let eventID: String
    @Environment(AppModel.self) private var model
    @State private var items: [ModerationItem] = []
    @State private var loaded = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                if loaded && items.isEmpty {
                    Text("Nothing to review.").foregroundStyle(Palette.textMuted).accessibilityIdentifier("moderation-empty")
                }
                ForEach(items, id: \.id) { item in
                    Card {
                        Color.clear.aspectRatio(4 / 3, contentMode: .fit)
                            .overlay { CachedPhoto(eventID: eventID, photoID: item.id, variant: "thumb", maxPixel: 600) }
                            .clipShape(.rect(cornerRadius: 8))
                            .accessibilityLabel("Uploaded photo")
                        HStack(spacing: 10) {
                            Button("Approve") { Task { await act(item, approve: true) } }.buttonStyle(.primary).accessibilityIdentifier("approve")
                            Button("Reject") { Task { await act(item, approve: false) } }.buttonStyle(.secondary).accessibilityIdentifier("reject")
                        }
                    }
                }
            }
            .padding(16)
            .readableWidth()
        }
        .task { await load() }
        .refreshable { await load() }
    }

    private func load() async {
        items = (try? await model.events.moderationQueue(eventID)) ?? items
        loaded = true
    }

    private func act(_ item: ModerationItem, approve: Bool) async {
        try? await model.events.moderate(eventID, photoID: item.id, approve: approve)
        UINotificationFeedbackGenerator().notificationOccurred(.success)
        await load()
    }
}

/// Members, with revoke (approve and organizer assignment stay on the web).
private struct MembersList: View {
    let eventID: String
    @Environment(AppModel.self) private var model
    @State private var members: [Member] = []
    @State private var confirm: Member?

    var body: some View {
        List {
            ForEach(members, id: \.userId) { member in
                HStack {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(member.email).foregroundStyle(Palette.text)
                        Text(statusText(member)).font(.footnote).foregroundStyle(Palette.textMuted)
                    }
                    Spacer()
                    if member.status == .approved && member.role == .attendee {
                        Button("Revoke") { confirm = member }
                            .foregroundStyle(Palette.dangerText)
                            .buttonStyle(.tapTarget)
                    }
                }
                .listRowBackground(Palette.surface)
                .accessibilityElement(children: .combine)
            }
        }
        .scrollContentBackground(.hidden)
        .task { members = (try? await model.events.members(eventID)) ?? [] }
        .alert("Revoke access?", isPresented: Binding(get: { confirm != nil }, set: { if !$0 { confirm = nil } }), presenting: confirm) { member in
            Button("Revoke", role: .destructive) {
                Task {
                    try? await model.events.revoke(eventID, userID: member.userId)
                    members = (try? await model.events.members(eventID)) ?? members
                }
            }
            Button("Cancel", role: .cancel) {}
        } message: { member in
            Text("\(member.email) will lose access to this event and its photos right away.")
        }
    }

    private func statusText(_ m: Member) -> String {
        let role = m.role == .organizer ? String(localized: "Organizer") : String(localized: "Attendee")
        let status: String = switch m.status {
        case .approved: String(localized: "Active")
        case .pending: String(localized: "Waiting for approval")
        case .revoked: String(localized: "Revoked")
        }
        return [role, status].joined(separator: " · ")
    }
}
