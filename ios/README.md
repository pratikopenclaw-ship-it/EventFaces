# EventFaces for iOS

Native SwiftUI app (iOS 17+, built with Xcode 27 / iOS 27 SDK). It talks to the same API as
the web app over a bearer-token transport that the backend proves equivalent to the web's
cookie transport (see SECURITY_QA_REPORT.md, "Mobile API").

## Setup

```bash
brew install xcodegen                 # once
ios/scripts/bootstrap.sh              # colours from design/tokens.json, API schema copy, Xcode project
open ios/EventFaces.xcodeproj
```

`EventFaces.xcodeproj` is generated from `project.yml` and not committed. If `xcode-select`
still points at the Command Line Tools, the scripts use `/Applications/Xcode.app` anyway; run
`sudo xcode-select -s /Applications/Xcode.app` to fix it for everything.

## Tests

```bash
docker compose -f docker-compose.yml -f docker-compose.e2e.yml up -d api   # e2e API on :8000
ios/scripts/test.sh               # derived-file checks + unit, integration and UI tests on iPhone and iPad
ios/scripts/test.sh --unit-only   # unit + integration only
```

- **Unit** (Swift Testing, `EventFacesTests`): deep-link parsing and tampering, device key
  and the refresh-signature format (test vector from the backend), Keychain protection
  class, single-flight refresh, session wipe on a refused refresh, 426 handling, no cookies
  or disk cache, colour assets = `design/tokens.json`, shipping plists (no ATS exceptions in
  Release), German strings.
- **Integration** (same target, `EF_INTEGRATION=1`): against the real e2e API: emailed-code
  sign-in, a device-signed refresh the server verifies, the magic link from the email, a
  copied session with a different key is ended, outdated versions get 426.
- **UI** (XCUITest, `EventFacesUITests`): onboarding, passwordless sign-in end to end (the
  code is read from the e2e server's captured mail), wrong code, theme, sign-out, and
  `performAccessibilityAudit` on every screen.
- **Phase 2–7 additions:**
  - Join, consent, capture and results UI flows.
  - `ContainerInspectionTests`: no selfie bytes on disk after a real search.
  - `AppAttestTests` (fake provider).
  - `ScreenMatrixUITests`: light/dark × default/largest text, also on iPhone 17e and iPhone 18 Pro Max.
  - `ContrastMeasureTests`.
  - Tap-target checks (`assertTapTarget`).
  - Shared audit helper: `UITestSupport.auditScreen`.
- `scripts/check-strings.py`: every UI string has a German translation.

## Architecture

- `App/`: entry point, `AppModel` (`@Observable` app state), deep-link routing into it.
- `Core/API/`: `openapi.json` (copied from `backend/openapi.json`) → swift-openapi-generator
  builds the typed client at build time. Re-run `bootstrap.sh` after backend API changes.
- `Core/Networking/`: URLSession with no cookies and no disk cache; `AuthMiddleware` adds
  the bearer token and `X-App-Version`, refreshes once on 401, reports 426.
- `Core/Auth/`: `SessionManager` (actor; access token in memory only; refresh token + device
  id in the Keychain, `AfterFirstUnlockThisDeviceOnly`, never synced), `DeviceKey` (Secure
  Enclave P-256 key; the simulator falls back to a Keychain software key), `AuthService`.
- `Core/Routing/DeepLink.swift`: strict parser for join / invite / sign-in / event links.
- `Core/Security/`: privacy shield over the app-switcher snapshot, logging rules.
- `Design/`: colour tokens (Asset Catalog, light + dark, generated), button styles,
  banner (icon + text, never colour alone), card.
- `Features/`: onboarding, sign-in, home, settings, update-required.

## Rules that keep the app no weaker than the web

- Tokens only in the Keychain (this device only); the access token never touches disk.
- No cookies, no URL cache, ATS without exceptions in Release (Debug allows only the local
  network for the docker-compose stack).
- Every refresh is signed by the device key; a copied refresh token is useless elsewhere.
- Never log tokens, codes, emails, URLs with queries or image data (`Core/Security/Log.swift`).
- Links are parsed strictly against the configured host; anything else is ignored.
- Colours come from `design/tokens.json` only; status is never colour-alone.
