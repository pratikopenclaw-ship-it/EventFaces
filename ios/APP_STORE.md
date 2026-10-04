# EventFaces for iOS: App Store and TestFlight

Everything here needs the **Apple Developer Program** account (paid) and a real domain.
Nothing in this file has been submitted or configured on any Apple account; it is the
checklist and the drafts for you to review and run.

## 1. App privacy ("nutrition label"): draft answers

Review against Apple's current questionnaire in App Store Connect › App Privacy. The
privacy manifest (`EventFaces/Resources/PrivacyInfo.xcprivacy`) declares the same.

**Tracking:** No. No third-party SDKs, analytics or advertising; no data shared with data brokers.

| Data type (Apple's category) | Collected? | Linked to the user? | Used for tracking? | Purpose | Notes |
|---|---|---|---|---|---|
| Contact Info › Email Address | Yes | Yes | No | App Functionality | Sign-in codes, account, "your photos are ready" emails |
| Identifiers › User ID | Yes | Yes | No | App Functionality | Account id |
| Identifiers › Device ID | Yes | Yes | No | App Functionality | A device record per signed-in install (name, app version, a public key for the device-bound session); not the advertising identifier |
| User Content › Photos or Videos | Yes | Yes | No | App Functionality | (1) Three selfies per search: sent for matching, **deleted right after matching, never stored**. (2) Event photos the user chooses to upload (stored for the event, organizer-moderated). |
| Sensitive Info | Review | | | | The selfie is turned into a face template for matching and discarded; Apple has no "biometric" category. Many apps answer "Sensitive Info" here. **Decide with your DPO.** |
| Usage Data, Diagnostics, Location, Financial, Health, Contacts, Browsing/Search History | No | | | | No crash reporting or analytics SDK; photos are re-encoded without location metadata |

## 2. App Review notes (paste into App Store Connect › App Review Information)

> **What the app does:** EventFaces lets people who attended an event find the photos they appear in, using a selfie. Only events the user joined (QR code, link, access code or invitation) are searched.
>
> **How to review:**
> 1. Open the app, tap Skip, then "Join an event".
> 2. Sign in with the demo address **{DEMO_EMAIL}**: the app emails a 6-digit code to this mailbox, which we monitor. Or use the code shown in the Notes field of this submission, refreshed for the review window.
> 3. Type the access code **{DEMO_CODE}** to join the demo event "{DEMO_EVENT}". It contains test photos of a consenting model.
> 4. Tap "Find my photos", read and accept the consent, then take the three selfies. In the simulator or without a matching face, the search returns "No photos of you yet", which is expected.
>
> **Face processing and deletion:** selfies are processed in memory on our EU servers (Germany) only to compare with the faces in this event's photos. They are deleted right after matching and never stored. We keep only the list of matched photos (7 days, or until the event's access ends). Consent is explicit, versioned and can be withdrawn in Settings › Privacy › "Delete my data". "Delete my account" (Settings) deletes the account and all its data in the app.
>
> **Permissions:** the camera (QR codes and selfies), adding photos to the library (only when the user taps Save; add-only), notifications (only when a search is queued and the user taps "Notify me"), Face ID (only if the user turns on the app lock).

Prepare before submitting:
- [ ] A demo account and demo event on **production** with test photos of a consenting person; record `{DEMO_EMAIL}`, `{DEMO_CODE}` and `{DEMO_EVENT}` above.
- [ ] A screen recording of the full flow (selfie → results), because reviewers may not match the demo face.

## 3. TestFlight and App Store checklist

**Apple Developer account (you)**
- [ ] Enroll the organization in the Apple Developer Program; note the **Team ID**.
- [ ] Register the bundle id `app.eventfaces.ios` with the capabilities **Push Notifications**, **Associated Domains** and **App Attest**.
- [ ] Create an **APNs key** (.p8), then set `APNS_KEY_P8`, `APNS_KEY_ID`, `APNS_TEAM_ID`, `APNS_TOPIC=app.eventfaces.ios`, `APNS_ENV=production` in `.env.prod` (DEPLOYMENT.md §9a).
- [ ] Set `APPLE_TEAM_ID` and `IOS_BUNDLE_ID` on the server; check `https://<domain>/.well-known/apple-app-site-association` (JSON, no redirect).

**Project**
- [ ] `project.yml`: set `DEVELOPMENT_TEAM`; Release `API_BASE_URL` and `APP_LINK_HOST` to the production domain (https).
- [ ] Entitlements: `aps-environment` = `production` for Release; add `com.apple.developer.associated-domains` = `applinks:<domain>`.
- [ ] Replace the placeholder app icon (`Assets.xcassets/AppIcon`).
- [ ] Bump `MARKETING_VERSION` / `CURRENT_PROJECT_VERSION`; set `IOS_MIN_SUPPORTED_VERSION` on the server to the oldest version you'll support.
- [ ] Build with **Xcode 27 / iOS 27 SDK** (required for uploads from April 2027; accepted now).

**Verification on real devices (the simulator can't cover these)**
- [ ] Secure Enclave device key: sign in, background the app for 20 minutes, reopen; the session refreshes.
- [ ] Camera: guided capture with the front camera in good and poor light; the two-rejections pause.
- [ ] VisionKit QR scanning of a printed event QR code.
- [ ] Universal Links: join, invite, sign-in and event links from Mail and Messages open the app.
- [ ] Push: queued search → "Notify me" → notification → tap opens the results. Organizer: guest upload → "Photos waiting for review".
- [ ] App lock with Face ID; app-switcher snapshot shows the privacy shield.
- [ ] Background download of a ZIP while the app is suspended; background upload of a large HEIC.
- [ ] Instruments: cold launch to interactive < 2 s; 60 fps scrolling in a 5,000-photo event (thumbnails are downsampled).
- [ ] App Attest (if enabled): attestation succeeds and is verified server-side in report-only mode before enforcing.

**App Store Connect**
- [ ] App Privacy answers (section 1), privacy policy URL `https://<domain>/privacy`, terms `https://<domain>/terms`. The legal texts are server-owned (same text on web and in the app); review them per LEGAL_REVIEW.md and set the `LEGAL_*` operator details first.
- [ ] License agreement: Apple's standard EULA applies; our Terms of Use are additional platform terms (linked in the description and shown in the app).
- [ ] Age rating; category Photo & Video.
- [ ] Screenshots: 6.9" and 6.5" iPhone, 13" iPad; light and dark.
- [ ] Localizations: English, German (the consent text's German version needs legal review).
- [ ] Export compliance: `ITSAppUsesNonExemptEncryption = NO` (standard HTTPS/TLS only).
- [ ] TestFlight internal testing, then external testing with the review notes above.
