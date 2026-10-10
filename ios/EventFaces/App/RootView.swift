import SwiftUI

struct RootView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        @Bindable var model = model
        Group {
            if model.updateRequired {
                UpdateRequiredView(updateURL: model.updateURL)
            } else if !model.hasSeenOnboarding {
                OnboardingView { model.hasSeenOnboarding = true }
            } else {
                MainView()
            }
        }
        .background(Palette.bg.ignoresSafeArea())
        .sheet(isPresented: $model.showSignIn) { SignInView().sheetContent() }
    }
}

/// One main screen (no system tab bar: its labels don't scale with Dynamic Type on iPad,
/// and content scrolling under the floating bar on iPhone can't be read).
struct MainView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        @Bindable var model = model
        NavigationStack(path: $model.path) {
            HomeView()
                .toolbar(.hidden, for: .navigationBar)
                .navigationDestination(for: String.self) { id in EventView(eventID: id) }
        }
        .sheet(isPresented: $model.showSettings) { SettingsSheet().sheetContent() }
        .sheet(isPresented: $model.showJoin) { JoinView().sheetContent() }
        .sheet(item: $model.requiredAcceptance) { AcceptLegalView(kind: $0).sheetContent() }
    }
}
