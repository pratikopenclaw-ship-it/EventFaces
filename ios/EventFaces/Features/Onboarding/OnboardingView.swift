import SwiftUI

/// Three short pages, skippable from the first one.
struct OnboardingView: View {
    let onFinish: () -> Void
    @State private var page = 0

    private let pages: [(symbol: String, title: LocalizedStringKey, body: LocalizedStringKey)] = [
        ("qrcode.viewfinder", "Join your event", "Scan the organizer's QR code, open their link, or type the access code."),
        ("person.crop.square", "Take a quick selfie", "Three short shots help us find you. Your selfie is deleted right after matching."),
        ("square.and.arrow.down", "Save your photos", "See the photos you're in and save the ones you like."),
    ]

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Spacer()
                Button("Skip", action: onFinish)
                    .foregroundStyle(Palette.accent)
                    .buttonStyle(.tapTarget)
                    .accessibilityIdentifier("onboarding-skip")
            }
            .padding(.horizontal)
            TabView(selection: $page) {
                ForEach(pages.indices, id: \.self) { i in
                    // Scrolls at large Dynamic Type sizes instead of clipping.
                    ScrollView {
                    VStack(spacing: 20) {
                        Image(systemName: pages[i].symbol)
                            .font(.system(size: 64, weight: .light))
                            .foregroundStyle(Palette.accent)
                            .accessibilityHidden(true)
                        Text(pages[i].title)
                            .font(.title.bold())
                            .fixedSize(horizontal: false, vertical: true)
                            .foregroundStyle(Palette.text)
                            .multilineTextAlignment(.center)
                            .accessibilityAddTraits(.isHeader)
                        Text(pages[i].body)
                            .font(.body)
                            .foregroundStyle(Palette.textMuted)
                            .multilineTextAlignment(.center)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    .padding(32)
                    .padding(.bottom, 40)  // clear of the page dots
                    .readableWidth()
                    }
                    .tag(i)
                }
            }
            .tabViewStyle(.page(indexDisplayMode: .always))
            .indexViewStyle(.page(backgroundDisplayMode: .always))
            Button(page == pages.count - 1 ? "Get started" : "Next") {
                if page == pages.count - 1 { onFinish() } else { withAnimation { page += 1 } }
            }
            .buttonStyle(.primary)
            .padding(24)
            .readableWidth()
            .accessibilityIdentifier("onboarding-next")
        }
        .background(Palette.bg.ignoresSafeArea())
    }
}
