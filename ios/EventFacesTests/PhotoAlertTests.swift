import Foundation
import Testing
@testable import EventFaces

@Suite("New-photo alerts")
struct PhotoAlertTests {
    let event = "3F2504E0-4F89-11D3-9A0C-0305E82C3301"

    @Test func aNewPhotosNoticeOpensTheEvent() {
        #expect(PushRoute.parse(["kind": "new_photos", "event_id": event]) == .newPhotos(eventID: event.lowercased()))
        #expect(PushRoute.parse(["kind": "new_photos", "event_id": "../../admin"]) == nil)
    }

    @MainActor
    @Test func aNewPhotosNoticeOpensTheEventPageNotResults() throws {
        let defaults = try #require(UserDefaults(suiteName: "alerts-\(UUID().uuidString)"))
        let model = AppModel(auth: .make(session: SessionManager(store: InMemorySecretStore()), config: testConfig, transport: FakeTransport()), config: testConfig, defaults: defaults)
        model.didSignIn(try JSONDecoder.api.decode(User.self, from: Data(userJSON().utf8)))
        model.handle(.newPhotos(eventID: "e1"))
        #expect(model.path == ["e1"] && model.openResultsFor == nil)
    }

    @Test func nothingShowsUntilTheUserHasSearchedHere() {
        let d = PhotoAlertDisplay(state: .init(enabled: true, subscribed: false), newPhotosSinceLastSearch: true, searchedThisVisit: false)
        #expect(!d.showBanner && !d.showToggle)
        #expect(!PhotoAlertDisplay(state: nil, newPhotosSinceLastSearch: true, searchedThisVisit: false).showToggle)
    }

    @Test func subscribedShowsTheToggleAndTheBannerOnlyForNewPhotos() {
        let state = PhotoAlertState(enabled: false, subscribed: true)
        let fresh = PhotoAlertDisplay(state: state, newPhotosSinceLastSearch: true, searchedThisVisit: false)
        #expect(fresh.showBanner && fresh.showToggle)  // the banner ignores the opt-out: it's in-app only
        #expect(!PhotoAlertDisplay(state: state, newPhotosSinceLastSearch: false, searchedThisVisit: false).showBanner)
    }

    @Test func aSearchOnThisScreenHidesTheBanner() {
        let d = PhotoAlertDisplay(state: .init(enabled: true, subscribed: true), newPhotosSinceLastSearch: true, searchedThisVisit: true)
        #expect(!d.showBanner && d.showToggle)
    }

    @Test func everyRoutedPushKindIsLocalized() throws {
        for lang in ["en", "de"] {
            let path = try #require(Bundle.main.path(forResource: lang, ofType: "lproj"))
            let bundle = try #require(Bundle(path: path))
            for kind in PushRoute.kinds {
                for part in ["title", "body"] {
                    let key = "push.\(kind).\(part)"
                    #expect(bundle.localizedString(forKey: key, value: nil, table: nil) != key, "\(lang) \(key)")
                }
            }
        }
    }
}
