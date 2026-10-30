import SwiftUI

/// What the event screen shows for new-photo alerts. A search subscribes, so nothing shows
/// until the user has searched this event. The banner is in-app only, so it ignores the
/// opt-outs; a search on this screen answers it.
struct PhotoAlertDisplay: Equatable {
    let showBanner: Bool
    let showToggle: Bool

    init(state: PhotoAlertState?, newPhotosSinceLastSearch: Bool, searchedThisVisit: Bool) {
        let subscribed = state?.subscribed == true
        showToggle = subscribed
        showBanner = subscribed && newPhotosSinceLastSearch && !searchedThisVisit
    }
}

/// The banner ("Scan again") and the per-event switch.
struct PhotoAlertsSection: View {
    let display: PhotoAlertDisplay
    let enabled: Bool
    let onToggle: (Bool) -> Void
    let onScan: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            if display.showBanner {
                VStack(alignment: .leading, spacing: 10) {
                    Text("New photos were added since your last scan")
                        .font(.body.weight(.semibold))
                        .foregroundStyle(Palette.text)
                        .fixedSize(horizontal: false, vertical: true)
                    Button("Scan again", action: onScan)
                        .buttonStyle(.secondary)
                        .accessibilityIdentifier("scan-again")
                }
                .padding(16)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(Palette.surface, in: .rect(cornerRadius: 14))
                .overlay(RoundedRectangle(cornerRadius: 14).stroke(Palette.border))
            }
            if display.showToggle {
                Toggle(isOn: Binding(get: { enabled }, set: onToggle)) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Tell me about new photos here").foregroundStyle(Palette.text)
                        Text("A notification or email, at most once a day. We only keep when you last searched, nothing about your face.")
                            .font(.footnote)
                            .foregroundStyle(Palette.textMuted)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                .tint(Palette.accent)
                .frame(minHeight: 56)
                .accessibilityIdentifier("event-photo-alerts")
            }
        }
    }
}
