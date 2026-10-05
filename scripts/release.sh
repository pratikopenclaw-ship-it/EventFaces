#!/usr/bin/env bash
# Cut a release: an annotated tag on main with notes from the merged pull requests, pushed to
# GitHub (plus a GitHub release). Deploy it on the server with scripts/deploy.sh <tag>.
#   scripts/release.sh v1.4.0          # asks before tagging and pushing
#   YES=1 scripts/release.sh v1.4.0    # no question
# Refuses unless: main is checked out, clean and equal to origin/main; the tag is new and
# greater than the latest release; and the CI workflow passed on this exact commit.
# NO_PUSH=1 tags locally only (rehearsals); it also skips the CI check, which needs GitHub.
set -euo pipefail
cd "$(dirname "$0")/.."

TAG="${1:?usage: scripts/release.sh vX.Y.Z[-rc.N]}"
die() { printf 'release: %s\n' "$*" >&2; exit 1; }
[[ "$TAG" =~ ^v[0-9]+\.[0-9]+\.[0-9]+(-rc\.[0-9]+)?$ ]] || die "tag must look like v1.2.3 or v1.2.3-rc.1"

[ "$(git rev-parse --abbrev-ref HEAD)" = main ] || die "check out main first"
if ! git diff --quiet || ! git diff --cached --quiet; then die "uncommitted changes"; fi
[ -z "$(git ls-files --others --exclude-standard)" ] || die "untracked files present"
if [ "${NO_PUSH:-0}" != 1 ]; then
  git fetch --quiet --tags origin main
  [ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] || die "main is not equal to origin/main (pull or push first)"
fi
! git rev-parse -q --verify "refs/tags/$TAG" >/dev/null || die "$TAG already exists"

PREV="$(git tag --list 'v*' | sort -V | tail -1)"
if [ -n "$PREV" ] && [ "$(printf '%s\n%s\n' "$PREV" "$TAG" | sort -V | tail -1)" != "$TAG" ]; then
  die "$TAG is not newer than $PREV"
fi

SHA="$(git rev-parse HEAD)"
if [ "${NO_PUSH:-0}" != 1 ]; then
  command -v gh >/dev/null || die "the GitHub CLI (gh) is needed to check CI"
  ci="$(gh run list --workflow ci.yml --commit "$SHA" --json conclusion,status --jq '[.[] | select(.status == "completed")][0].conclusion' 2>/dev/null || true)"
  [ "$ci" = success ] || die "CI has not passed on $SHA (latest completed run: ${ci:-none})"
fi

NOTES="$(mktemp)"
trap 'rm -f "$NOTES"' EXIT
{
  echo "EventFaces $TAG"
  echo
  range="${PREV:+$PREV..}HEAD"
  merged="$(git log --merges --format='%s' "$range" | sed -E 's/^Merge (pull request|PR) #?([0-9]+)[^:]*:? ?/#\2 /')"
  if [ -n "$merged" ]; then
    echo "Merged:"; printf '%s\n' "$merged" | sed 's/^/- /'
  else
    echo "Changes:"; git log --no-merges --format='- %s' "$range"
  fi
  echo
  echo "Commit: $SHA${PREV:+ (previous release: $PREV)}"
} >"$NOTES"

cat "$NOTES"
echo
if [ "${YES:-0}" != 1 ]; then
  action="Tag $TAG and push it"
  [ "${NO_PUSH:-0}" = 1 ] && action="Tag $TAG locally (no push)"
  read -r -p "$action? [y/N] " answer
  [ "$answer" = y ] || [ "$answer" = Y ] || die "cancelled"
fi
git tag -a "$TAG" -F "$NOTES"
if [ "${NO_PUSH:-0}" != 1 ]; then
  git push origin "$TAG"
  prerelease=()
  [[ "$TAG" == *-rc.* ]] && prerelease=(--prerelease)  # release candidates (UAT builds)
  gh release create "$TAG" --verify-tag --title "$TAG" --notes-file "$NOTES" ${prerelease[@]+"${prerelease[@]}"}  # bash 3.2-safe empty array
fi
echo "released $TAG; deploy on the server with: scripts/deploy.sh $TAG"
