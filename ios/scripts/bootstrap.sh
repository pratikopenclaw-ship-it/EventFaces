#!/usr/bin/env bash
# Regenerate everything derived: colour assets from design/tokens.json, the API schema
# copy from backend/openapi.json, and EventFaces.xcodeproj from project.yml.
set -euo pipefail
source "$(dirname "$0")/env.sh"
python3 "$IOS_DIR/scripts/gen-colors.py"
python3 "$IOS_DIR/scripts/sync-openapi.py"  # copy, adapted for the generator (nullable fields)
(cd "$IOS_DIR" && xcodegen generate --quiet)
echo "EventFaces.xcodeproj generated"
