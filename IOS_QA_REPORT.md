# EventFaces iOS: QA report

Scope: the native iOS app in `ios/` (SwiftUI, iOS 17+, built with Xcode 27 / iOS 27 SDK) and
the backend changes made for it. The same standard as the web audit (SECURITY_QA_REPORT.md)
applies: every finding is fixed immediately with a regression test, tests are never weakened,
and only the local docker-compose stack, simulators and test data are used.

Backend findings for the mobile API (Phase 0) are in SECURITY_QA_REPORT.md, "Mobile API".

## Status by phase

| Phase | Scope | Status |
|---|---|---|
| 0 | Mobile API (bearer + device-bound sessions, codes, push, AASA, versions, logos) | Done, see SECURITY_QA_REPORT.md |
| 1 | Foundation: project, tokens, components, theme, API client, Keychain + Secure Enclave auth, deep links, en/de | Done |
| 2 | Join (link, QR, code, invite), consent, guided capture, search incl. queued mode | Done |
| 3 | Results tiers, viewer, feedback, report/removal, downloads (single, ZIP via share sheet) | Done |
| 4 | Push + routing, account & privacy (delete data / account, devices, theme, app lock) | Done (push end to end needs an Apple account: R-iOS-1) |
| 5 | Guest upload (PhotosPicker, limits first, HEIC, background presigned PUTs, moderation states) | Done |
| 6 | Organizer lite (events, QR + link share, moderation, members with revoke) | Done |
| 7 | App Attest (report-only), privacy manifest, App Store drafts, QA | **Done** in the simulator (gate below); device-only items listed in ios/APP_STORE.md |

## Findings (iOS)

| ID | Sev | Found by | Finding | Fix | Regression |
|---|---|---|---|---|---|
| IOS-001 | Medium | `DeepLinkTests` (tamper list) | Debug builds accepted an `https` link to the right host with an explicit port | Ports only for `localhost` in Debug; never in Release | `DeepLinkTests.rejectsTamperedLinks` (`:8443`) |
| IOS-002 | Medium | Code review while integrating the generator | swift-openapi-generator **silently skips OpenAPI 3.1 nullable fields** (`anyOf: [T, null]`): `accent_color`, `date`, `given_at`, search-status details and ~40 more were missing from the Swift types (data loss without an error) | `ios/scripts/sync-openapi.py` rewrites nullable fields as optional `T` when copying the schema | `test.sh` fails if the copy is stale (`sync-openapi.py --check`); build log has 0 "Schema null not supported" warnings |
| IOS-003 | Low | `performAccessibilityAudit` | "Cancel" in the sign-in sheet failed contrast: iOS 27 draws toolbar buttons on translucent glass | Our own sheet header in token colours (`SheetHeader`) | `AppUITests.testPasswordlessSignInThemeAndSignOut` (audit) |
| IOS-004 | Low | Audit | Onboarding and sign-in text clipped at large Dynamic Type sizes | Screens scroll; texts wrap (`fixedSize(vertical:)`) | `testOnboardingCanBeSkippedAndIsAccessible`, sign-in audit |
| IOS-005 | Low | UI test | The code field didn't take keyboard focus when the code step appeared | Focus once the field is on screen | `waitForFocus(code-field)` in both sign-in UI tests |
| IOS-006 | Low | Audit | Disabled primary buttons (50 % opacity) failed contrast | Disabled = `text-muted` on `surface-2` (a token pair ≥ 4.5:1) | Sign-in audit with the disabled "Send code" |
| IOS-007 | Low | Audit | Settings built on `Form`: contrast through system materials, labels that don't scale, a clipped row | Settings rebuilt from our own components | Settings audit (light and dark, top and scrolled) |
| IOS-008 | Low | Audit (iPhone and iPad) | System tab bar: content scrolling under the floating bar (iPhone) can't be read; iPad's top tab bar labels don't scale with Dynamic Type | No tab bar: one home screen with a 44 pt Settings button; Settings in a sheet | All UI audits on iPhone 17 and iPad Air |
| IOS-009 | Low | Recorded demo walkthrough | "You're signed in." banner stayed on screen after signing out | Sign-out clears notices | `AppModelTests.signingOutClearsTheSignedInBanner` (fails on the old code) |
| IOS-010 | Low | Code review | Selfie rejection reasons were shown in the server's English to German users | The app maps rejection codes to localized messages; unknown codes fall back to the server text | `RejectionMessageTests` (every code in backend `selfie_quality.MESSAGES` must be mapped) |
| IOS-011 | Medium | Unit test (crash) | Wiping the selfie buffers after a search crashed with an exclusivity violation (overlapping access to the shot array) | Wipe each buffer in place through one `withUnsafeMutableBytes` access | `CaptureModelTests` (wipe after search) |
| IOS-012 | Medium | Calibration against the server | The Vision → InsightFace yaw sign was assumed inverted; left/right guidance would have asked people to turn the wrong way | Calibrated on the same frames as the server (`yawSign = +1`), as on web | `FaceGuidanceTests` with the e2e test selfies |
| IOS-013 | Low | Audit (gallery) | Result thumbnails spilled over neighbouring cells and the section heading, which then failed contrast | Square cells, photo clipped inside | Phase 2 UI test audit on the gallery |
| IOS-014 | Low | UI test | A result tile ignored taps until its thumbnail had loaded (`Color.clear` isn't hit-testable) | `contentShape` on the tile | `Phase2UITests` happy path taps the first tile immediately |
| IOS-017 | Medium | UI test + accessibility tree | **Tap targets smaller than 44 pt:** 11 text buttons (Close in sheets and the viewer, Done, Cancel, Skip, Select, Retry, Revoke, Sign out device, resend code) had `.frame(minWidth: 44, minHeight: 44)` outside the Button. That enlarges the layout, not the tappable area: the real targets were ~43 × 20 pt. The audit didn't flag them | `TapTargetButtonStyle` (`.tapTarget`): the frame and tap shape sit on the label; disabled uses the readable muted token | `assertTapTarget` (≥ 44 × 44 pt) on Skip, Cancel, Settings, Done, Select, Close and the viewer's Close |
| IOS-018 | Low | UI test | Container identifiers replaced the identifiers of the controls inside: the viewer's (Close, verdicts, Save, Report all read `viewer`) and the results screen's, applied after `.safeAreaInset`, which also covered the selection action bar (Save, Share, All (ZIP) read `results`). Automation and the happy-path test couldn't find them | Identifiers on the pager / the scroll view itself, before `.safeAreaInset`; the remaining container identifiers sit on scroll views, which keep their children's | `Phase2UITests` happy path opens the viewer, marks "Not me", closes it |
| IOS-020 | Low | Screen matrix (audit) | The access-code and 6-digit code fields didn't scale with Dynamic Type: `Font.monospaced()` / `.monospacedDigit()` on the *font* gives the text field a fixed-size font | The scaling view modifiers (`.fontDesign(.monospaced)`, `.monospacedDigit()`) | `ScreenMatrixUITests` (join and sign-in screens, default and largest text) |
| IOS-021 | Low | Screen matrix (largest text) | Primary/secondary button labels had no vertical padding: at the largest sizes the text touched the button's edges | 12 pt vertical padding inside the 50 pt minimum (no change at default sizes) | `ScreenMatrixUITests` home screen at AX-XXXL |
| IOS-022 | Low | Screen matrix | The sign-in code step uses a number pad, which has no key to close it | Sign-in and join forms close the keyboard as soon as the content scrolls | `ScreenMatrixUITests` (audit clears the keyboard by scrolling) |
| IOS-023 | Low | Screen matrix on iPad (audit: "potentially inaccessible text") | The access-code, email and 6-digit code fields had **no accessibility label** (VoiceOver read an empty field), and their placeholder used the system's faint placeholder grey, below 4.5:1 on the light surface | Explicit labels; placeholders drawn in the muted text token (≥ 4.5:1, tested) | `ScreenMatrixUITests` on iPad, light and dark |
| IOS-024 | Low | Screen matrix on iPad (light) | The home screen's status notice ("You're signed in.") stayed up while a sheet was open; on iPad it sat dimmed and unreadable behind the form sheet (the audit flagged it as text it couldn't read). It was also dismissible by tap only, not with VoiceOver | Notices clear when Join or Settings opens (they are stale by then); a "Dismiss" accessibility action | `AppModelTests.openingASheetClearsTheNotice`; `ScreenMatrixUITests` on iPad |
| IOS-025 | — | Audit on iPad (test method) | The audit failed "Delete my account" (Settings, dark) on contrast at some scroll offsets and not others. Its rendered pixels measure **9.1:1** (`#FFA3A3` on `#171A21`), the same colour in the same kind of row passes on the same screen, and the identical screen passes on iPhone. Ruled out: scroll motion, the card border, the row component | The audit helper checks every contrast failure against the rendered pixels: the element's background against its most contrasting frequent colour. A failure stands unless that measures **≥ 4.5:1**, and each overruled verdict is logged with the ratio and a screenshot. **This is a change to the test method**: `ContrastMeasureTests` proves the measurement fails 1.7:1 text, passes the 9:1 row, and leaves a blank element to the audit | `ContrastMeasureTests` (3) |
| IOS-026 | Low | Audit (Settings, iPad) | Under our opaque sheet headers, iOS 26+'s soft scroll-edge fade dimmed the first rows | `hardScrollEdges()` on every sheet and full-screen flow with our own header; screens under the system navigation bar keep the fade | Settings audit on iPad |
| IOS-027 | Medium | Container inspection test | The simulator's fake camera (Debug builds, `-fake-camera`) loaded its test frames with `URLSession.shared`, whose URL cache writes responses to disk (`Cache.db`, `httpstorages.sqlite`). These are test images, not real selfies, and Release builds don't contain the fake camera. Still, it broke "selfie frames never reach disk" in the build we test with and could have hidden a real regression from the container check. The integration tests did the same | The fake camera uses the app's no-cache network session; tests use an ephemeral session without a cache (`TestNet.session`) | `ContainerInspectionTests` runs the fake camera inside its measured window; mutation-checked (restoring `URLSession.shared` fails it) |
| IOS-019 | — | Audit on iPad | "Delete my data", lying just below the bottom edge of the Settings form sheet, was measured against what's behind the sheet (contrast). Not a product bug; the overlap rule only knew about bars and the keyboard | The shared audit helper (`UITestSupport.auditScreen`) treats elements not fully inside their innermost scroll view (the sheet's, not the full-window one behind it that stays in the tree) or the window like those under a bar: re-audited after scrolling, and they must pass there (pass 2 still fails anything that is still hidden) | All UI suites use the one helper |
| IOS-015 | — | Self-review of tests | One UI test called `try? audit()`, which would have swallowed audit failures (a weakened test) | `try audit()` everywhere; grep check before each run | — |
| IOS-016 | Low | Backend fuzz test (Phase 7) | App Attest: a corrupted certificate in an attestation raised library errors (500) instead of a recorded failure | All parser errors map to `AttestError("malformed")` | `test_hostile_input_only_ever_raises_attest_errors` (see SECURITY_QA_REPORT.md) |

## Backend changes made for Phases 1–2 (re-tested)

- **Readable operation ids** (`<tag>_<function>`) for the generated client; uniqueness and format are tested (`test_openapi_contract.py`).
- **Typed responses** for app-facing endpoints that returned free-form dicts (`/api/selfie-requirements`, `/api/events/{id}/search-status`, `/api/drive/service-account`); same JSON.
- **Consent text is server-owned** (`services/consent_text.py`, English + German draft): returned with `/api/me/face-consent` in the request's language, rendered by web and app. Any wording change fails `test_consent_text.py` until `FACE_CONSENT_VERSION` is bumped, so a changed text always re-asks users. **The German text is a draft that needs legal review.**
- **`POST /api/join/by-code`** (the app's "type the access code"): the same membership rules as the slug join (shared `_admit`: invite-only, ended, revoked never re-approved, race-safe insert), with a **global** lockout per user and per IP (5 wrong codes → 15 min) because one endpoint covers every event. Tests: `test_join_by_code.py` (5), authorization matrix (both transports), rate-limit contract; the lockout was mutation-checked.

## App Attest (Phase 7, report-only)

After sign-in, the app attests a fresh App Attest key over a single-use server challenge. Every device-signed refresh then carries an assertion over the refresh message. The server records the results on the device and never blocks a request (owner decision: report-only first).
- The simulator has no App Attest. `AppAttestTests` (6) cover the client path with a fake provider:
  - the challenge hash
  - a verified key is kept, a failed one isn't
  - nothing happens when the server has it off or the device can't
  - the assertion hashes the exact signed message
  - refreshes still work when an assertion fails
  - sign-out forgets the key
- Server checks: SECURITY_QA_REPORT.md, "App Attest, report-only".

## Phase 7 gate (2026-10-02, `ios/scripts/test.sh`, exit 0)

| Simulator (iOS 27) | Suites | Result |
|---|---|---|
| iPhone 17 | Unit + integration (Swift Testing, 24 suites) and all UI tests | **93 passed, 0 failed** |
| iPad Air 11-inch (M4) | The same | **93 passed, 0 failed** |
| iPhone 17e (smallest) | Screen matrix: light/dark × default/largest text | **4 passed** |
| iPhone 18 Pro Max (largest) | Screen matrix | **4 passed** |

Also covered:
- derived files current: API schema copy, colour assets, strings (250 UI strings, all with German);
- the container check after a real search (no selfie bytes anywhere; only the photo cache, protected and excluded from backup);
- App Attest client tests.

**Audit verdicts overruled by the rendered-pixel check in this gate (IOS-025), all on iPad:**
- "About": 17.3:1
- "Delete my account": 9.1:1
- "This device": 6.7:1

None of them came anywhere near 4.5:1.

**Not covered in the simulator** (needs a real device and the Apple Developer account; checklist in `ios/APP_STORE.md`):
- App Attest on hardware
- Secure Enclave
- camera and VisionKit
- push and Universal Links end to end
- Face ID app lock
- Instruments launch and scrolling budgets
- Network Link Conditioner runs

## Accessibility method

Every screen is audited with `performAccessibilityAudit` in a UI test. Issues are fixed, not
filtered. One rule handles overlap: an issue on an element that sits under a system bar or the
keyboard (or that the audit can't name) triggers a second audit in a clear state (keyboard
dismissed, content scrolled clear), which must pass; an element that is overlapped in both
passes fails.

## Residual risks

| ID | Risk | Mitigation / plan |
|---|---|---|
| R-iOS-1 | Universal Links and push can't be verified end to end without an Apple Developer account and a real domain | AASA content tests (web), link parser tamper tests, fake APNs server tests (backend); verify on TestFlight (Phase 7) |
| R-iOS-2 | Camera, Secure Enclave and VisionKit QR scanning aren't available in the simulator | The simulator uses the e2e test selfies (fake camera), a Keychain software key, and a scanned-payload hook; the device paths are covered in Phase 7 on real hardware |
| R-iOS-3 | German consent text is a draft translation | Legal review before release (DEPLOYMENT.md go/no-go) |

## How to re-run

```bash
brew install xcodegen
docker compose -f docker-compose.yml -f docker-compose.e2e.yml up -d api   # e2e API on :8000
ios/scripts/test.sh            # derived files + unit + integration + UI tests on iPhone 17 and iPad Air
```
