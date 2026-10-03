import PhotosUI
import SwiftUI

/// Guest uploads: choose event photos (the photo library is allowed here, unlike selfies),
/// see the limits first, watch each upload, retry, and follow moderation.
struct UploadView: View {
    let event: EventDetail
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var picked: [PhotosPickerItem] = []
    @State private var items: [UploadItem] = []
    @State private var uploads: [MyUpload] = []

    struct UploadItem: Identifiable, Equatable {
        let id = UUID()
        let name: String
        var progress: Double = 0
        var state: State = .waiting
        var picker: PhotosPickerItem?
        enum State: Equatable { case waiting, uploading, done(pendingReview: Bool), failed(String) }
    }

    private var maxMB: Int { Int((event.uploadMaxBytes ?? 25 * 1024 * 1024) / (1024 * 1024)) }

    var body: some View {
        VStack(spacing: 0) {
            SheetHeader(title: "Add photos", closeLabel: "Close") { dismiss() }
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    Text("Share your photos from \(event.name). JPEG, PNG or HEIC, up to \(maxMB) MB each.")
                        .foregroundStyle(Palette.textMuted).fixedSize(horizontal: false, vertical: true)
                        .accessibilityIdentifier("upload-limits")
                    Text("The organizer reviews photos before others can see them. Photos are re-saved without location data.")
                        .font(.footnote).foregroundStyle(Palette.textMuted).fixedSize(horizontal: false, vertical: true)
                    PhotosPicker(selection: $picked, maxSelectionCount: 20, matching: .images, photoLibrary: .shared()) {
                        Label("Choose photos", systemImage: "photo.on.rectangle.angled")
                    }
                    .buttonStyle(.primary)
                    .accessibilityIdentifier("choose-photos")
                    ForEach($items) { $item in UploadRow(item: item) { Task { await retry(item.id) } } }
                    if !uploads.isEmpty {
                        Text("Your uploads").font(.headline).foregroundStyle(Palette.text).padding(.top, 8).accessibilityAddTraits(.isHeader)
                        ForEach(uploads, id: \.id) { upload in
                            HStack {
                                Text(upload.originalFilename ?? String(localized: "Photo")).foregroundStyle(Palette.text).lineLimit(1)
                                Spacer()
                                Text(statusLabel(upload)).font(.footnote).foregroundStyle(Palette.textMuted)
                            }
                            .frame(minHeight: 44)
                            .accessibilityElement(children: .combine)
                        }
                    }
                }
                .padding(20)
                .readableWidth()
            }
        }
        .background(Palette.bg.ignoresSafeArea())
        .task { await refresh() }
        .onChange(of: picked) { _, new in
            let added = new.map { UploadItem(name: $0.itemIdentifier ?? "photo", picker: $0) }
            items.append(contentsOf: added)
            picked = []
            Task { for item in added { await upload(item.id) } }
        }
    }

    private func statusLabel(_ upload: MyUpload) -> LocalizedStringKey {
        switch upload.status {
        case .pendingReview: "Waiting for approval"
        case .published: "Published"
        case .rejected: "Not approved"
        case .removed: "Removed"
        default: "Processing"
        }
    }

    private func upload(_ id: UUID) async {
        guard let i = items.firstIndex(where: { $0.id == id }), let picker = items[i].picker else { return }
        items[i].state = .uploading
        items[i].progress = 0
        do {
            guard let data = try await picker.loadTransferable(type: Data.self) else { throw UploadError.unsupportedType }
            let type = Self.contentType(data)
            guard let type else { throw UploadError.unsupportedType }
            guard data.count <= event.uploadMaxBytes ?? Int.max else { throw UploadError.tooLarge }
            let ext = type == "image/heic" ? "heic" : (type == "image/png" ? "png" : "jpg")
            let ticket = try await model.events.startUpload(eventID: event.id, filename: "photo.\(ext)", contentType: type, size: data.count)
            let file = try UploadManager.stage(data, name: "photo.\(ext)")
            defer { try? FileManager.default.removeItem(at: file) }
            try await UploadManager.shared.put(file: file, to: ticket.url, contentType: ticket.contentType) { p in
                Task { @MainActor in if let j = items.firstIndex(where: { $0.id == id }) { items[j].progress = p } }
            }
            let done = try await model.events.completeUpload(eventID: event.id, photoID: ticket.photoID)
            if let j = items.firstIndex(where: { $0.id == id }) { items[j].state = .done(pendingReview: done.status == .pendingReview); items[j].progress = 1 }
            UINotificationFeedbackGenerator().notificationOccurred(.success)
            await refresh()
        } catch {
            if let j = items.firstIndex(where: { $0.id == id }) { items[j].state = .failed(Self.message(error)) }
        }
    }

    private func retry(_ id: UUID) async { await upload(id) }

    private func refresh() async { uploads = (try? await model.events.myUploads(eventID: event.id)) ?? uploads }

    /// Magic bytes (the server checks them again).
    static func contentType(_ data: Data) -> String? {
        let b = [UInt8](data.prefix(12))
        if b.count >= 3, b[0] == 0xFF, b[1] == 0xD8, b[2] == 0xFF { return "image/jpeg" }
        if b.count >= 8, b[0..<8] == [0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A] { return "image/png" }
        if b.count >= 12, b[4..<8] == [0x66, 0x74, 0x79, 0x70] {
            let brand = String(decoding: b[8..<12], as: UTF8.self)
            if ["heic", "heix", "hevc", "hevx", "heim", "heis", "hevm", "hevs", "mif1", "msf1"].contains(brand) { return "image/heic" }
        }
        return nil
    }

    static func message(_ error: Error) -> String {
        switch error {
        case UploadError.tooLarge: String(localized: "This photo is too large.")
        case UploadError.unsupportedType: String(localized: "This file type isn't supported. Use JPEG, PNG or HEIC.")
        case UploadError.quotaReached: String(localized: "You've reached the upload limit for this event.")
        case UploadError.notAllowed: String(localized: "Uploads aren't open for this event.")
        case UploadError.rateLimited: String(localized: "Too many uploads at once. Wait a little, then retry.")
        case UploadManager.Failure.network, AppError.offline, is URLError: String(localized: "The upload didn't finish. Check your connection and retry.")
        default: String(localized: "Something went wrong on our side. Try again in a moment.")
        }
    }
}

private struct UploadRow: View {
    let item: UploadView.UploadItem
    let onRetry: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Image(systemName: icon).foregroundStyle(color).accessibilityHidden(true)
                Text(label).foregroundStyle(Palette.text).fixedSize(horizontal: false, vertical: true)
                Spacer()
                if case .failed = item.state {
                    Button("Retry", action: onRetry).foregroundStyle(Palette.accent).buttonStyle(.tapTarget)
                }
            }
            if item.state == .uploading {
                ProgressView(value: item.progress).tint(Palette.accent)
                    .accessibilityLabel("Upload progress")
            }
        }
        .padding(12)
        .background(Palette.surface, in: .rect(cornerRadius: 12))
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("upload-row")
    }

    private var label: String {
        switch item.state {
        case .waiting: String(localized: "Waiting to upload")
        case .uploading: String(localized: "Uploading…")
        case let .done(pending): pending ? String(localized: "Uploaded. Waiting for approval.") : String(localized: "Uploaded and published.")
        case let .failed(message): message
        }
    }

    private var icon: String {
        switch item.state {
        case .done: "checkmark.circle.fill"
        case .failed: "exclamationmark.triangle.fill"
        default: "arrow.up.circle"
        }
    }

    private var color: Color {
        switch item.state {
        case .done: Palette.success
        case .failed: Palette.danger
        default: Palette.accent
        }
    }
}
