#!/usr/bin/env bash
# Everything the iOS app is checked with:
#   1. derived files are current (colours, API schema copy, strings)
#   2. unit + integration tests on an iPhone and an iPad simulator (integration needs the
#      e2e API: docker compose -f docker-compose.yml -f docker-compose.e2e.yml up -d api)
#   3. UI tests (XCUITest) on both simulators, incl. accessibility audits
#   4. the screen matrix (light/dark x default/largest text) on the smallest and largest iPhone
# Usage: scripts/test.sh [--unit-only | --no-api]
#   --no-api: derived files + unit tests without the integration suites (CI's macOS runners
#             have no Docker, so no e2e API); the local gate stays the full run.
set -euo pipefail
source "$(dirname "$0")/env.sh"
cd "$IOS_DIR"

echo "==> derived files"
python3 scripts/sync-openapi.py --check
python3 scripts/check-strings.py
scripts/bootstrap.sh >/dev/null
git -C "$REPO_DIR" diff --quiet -- ios/EventFaces/Resources/Assets.xcassets || { echo "colour assets were stale (now regenerated): commit them"; exit 1; }

INTEGRATION=1
if [[ "${1:-}" == "--no-api" ]]; then
  INTEGRATION=0
else
  curl -sf -o /dev/null http://localhost:8000/api/health || { echo "e2e API not reachable on :8000 (start the e2e stack)"; exit 1; }
fi

ONLY=()
[[ "${1:-}" == "--unit-only" || "${1:-}" == "--no-api" ]] && ONLY=(-only-testing:EventFacesTests)
STATUS=0
for SIM in "$SIM_IPHONE" "$SIM_IPAD"; do
  echo "==> tests on $SIM"
  LOG="build/test-${SIM// /_}.log"
  RESULT="build/results-${SIM// /_}.xcresult"
  rm -rf "$RESULT"
  TEST_RUNNER_EF_INTEGRATION=$INTEGRATION xcodebuild test \
    -project EventFaces.xcodeproj -scheme EventFaces \
    -destination "platform=iOS Simulator,name=$SIM" \
    -derivedDataPath build/dd -resultBundlePath "$RESULT" \
    -skipPackagePluginValidation -skipMacroValidation ${ONLY[@]+"${ONLY[@]}"} > "$LOG" 2>&1 || STATUS=1
  grep -E "(✘|recorded an issue|error:.*Test|Test run with|Executed [0-9]+ tests|\*\* TEST)" "$LOG" | grep -v "/SourcePackages/" | tail -25
done
if [[ "${1:-}" != "--unit-only" && "${1:-}" != "--no-api" ]]; then
  for SIM in "$SIM_SMALL" "$SIM_LARGE"; do
    echo "==> screen matrix on $SIM"
    LOG="build/test-${SIM// /_}.log"
    RESULT="build/results-${SIM// /_}.xcresult"
    rm -rf "$RESULT"
    xcodebuild test \
      -project EventFaces.xcodeproj -scheme EventFaces \
      -destination "platform=iOS Simulator,name=$SIM" \
      -derivedDataPath build/dd -resultBundlePath "$RESULT" \
      -skipPackagePluginValidation -skipMacroValidation -only-testing:EventFacesUITests/ScreenMatrixUITests > "$LOG" 2>&1 || STATUS=1
    grep -E "(error:.*Test|Executed [0-9]+ tests|\*\* TEST)" "$LOG" | tail -10
  done
fi
exit $STATUS
