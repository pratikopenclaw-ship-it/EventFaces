import SwiftUI

/// The server's versioned consent text (same words as the web), then explicit agreement.
struct ConsentView: View {
    let info: ConsentInfo
    let onGiven: () -> Void
    let onCancel: () -> Void
    @Environment(AppModel.self) private var model
    @State private var agreed = false
    @State private var busy = false
    @State private var failed = false

    var body: some View {
        VStack(spacing: 0) {
            SheetHeader(title: "Consent", onClose: onCancel)
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    Text(info.text.title).font(.title2.bold()).foregroundStyle(Palette.text).accessibilityAddTraits(.isHeader)
                    Text(info.text.intro).foregroundStyle(Palette.textMuted).fixedSize(horizontal: false, vertical: true)
                    ForEach(info.text.sections, id: \.heading) { section in
                        VStack(alignment: .leading, spacing: 6) {
                            Text(section.heading).font(.headline).foregroundStyle(Palette.text).accessibilityAddTraits(.isHeader)
                            ForEach(section.paragraphs, id: \.self) { p in
                                Text(p).foregroundStyle(Palette.textMuted).fixedSize(horizontal: false, vertical: true)
                            }
                        }
                    }
                    if failed { Banner(kind: .error, text: Text("Couldn't save your consent. Try again in a moment.")) }
                    Toggle(isOn: $agreed) {
                        Text(info.text.agreement).foregroundStyle(Palette.text).fixedSize(horizontal: false, vertical: true)
                    }
                    .toggleStyle(CheckboxStyle())
                    .accessibilityIdentifier("consent-checkbox")
                    Button {
                        Task { await give() }
                    } label: {
                        if busy { ProgressView().tint(Palette.onAccent) } else { Text(info.text.action) }
                    }
                    .buttonStyle(.primary)
                    .disabled(!agreed || busy)
                    .accessibilityIdentifier("consent-continue")
                }
                .padding(20)
                .readableWidth()
            }
        }
        .background(Palette.bg.ignoresSafeArea())
    }

    private func give() async {
        busy = true
        defer { busy = false }
        do {
            _ = try await model.events.giveConsent(version: info.version)
            onGiven()
        } catch {
            failed = true
        }
    }
}

/// A checkbox (not a switch): consent is an explicit "I agree".
struct CheckboxStyle: ToggleStyle {
    func makeBody(configuration: Configuration) -> some View {
        Button {
            configuration.isOn.toggle()
        } label: {
            HStack(alignment: .firstTextBaseline, spacing: 12) {
                Image(systemName: configuration.isOn ? "checkmark.square.fill" : "square")
                    .font(.title3)
                    .foregroundStyle(configuration.isOn ? Palette.accent : Palette.textMuted)
                    .accessibilityHidden(true)
                configuration.label
            }
            .padding(12)
            .frame(maxWidth: .infinity, minHeight: 44, alignment: .leading)
            .background(Palette.surface2, in: .rect(cornerRadius: 10))
        }
        .buttonStyle(.plain)
        .accessibilityAddTraits(configuration.isOn ? [.isSelected] : [])
    }
}
