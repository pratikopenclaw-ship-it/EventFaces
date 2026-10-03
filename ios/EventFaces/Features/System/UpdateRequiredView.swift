import SwiftUI

/// Shown when the server answers 426: this version has a known security fix pending.
struct UpdateRequiredView: View {
    let updateURL: URL?
    @Environment(\.openURL) private var openURL

    var body: some View {
        ScrollView {
        VStack(spacing: 20) {
            Image(systemName: "arrow.down.app")
                .font(.system(size: 60, weight: .light))
                .foregroundStyle(Palette.accent)
                .accessibilityHidden(true)
            Text("Update EventFaces")
                .font(.title.bold())
                .foregroundStyle(Palette.text)
                .accessibilityAddTraits(.isHeader)
            Text("This version is no longer supported. Update the app to keep finding your photos.")
                .multilineTextAlignment(.center)
                .foregroundStyle(Palette.textMuted)
            if let updateURL {
                Button("Open the App Store") { openURL(updateURL) }
                    .buttonStyle(.primary)
            }
        }
        .padding(32)
        .readableWidth()
        }
        .background(Palette.bg.ignoresSafeArea())
        .accessibilityIdentifier("update-required")
    }
}
