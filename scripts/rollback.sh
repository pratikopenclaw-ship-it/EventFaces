#!/usr/bin/env bash
# Roll the server back to the previous release (or to the given tag), the same way a failed
# deploy does: alembic downgrade if the schema changed (backup restore if that fails), check
# out, build, start, release check.
#   scripts/rollback.sh            # to the release before the current one
#   scripts/rollback.sh v1.3.2     # to a specific, previously deployed tag
set -euo pipefail
exec "$(dirname "$0")/deploy.sh" --rollback "$@"
