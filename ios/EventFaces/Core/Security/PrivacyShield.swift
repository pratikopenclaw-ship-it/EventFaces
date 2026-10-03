import SwiftUI

/// Shown over everything while the app is inactive or in the background (the snapshot
/// iOS keeps for the app switcher is taken then).
struct PrivacyShield: View {
    var body: some View {
        ZStack {
            Palette.bg.ignoresSafeArea()
            Image(systemName: "person.crop.square.badge.camera")
                .font(.system(size: 56))
                .foregroundStyle(Palette.accent)
                .accessibilityHidden(true)
        }
        .accessibilityIdentifier("privacy-shield")
    }
}
