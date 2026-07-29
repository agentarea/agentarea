#!/usr/bin/env bash
# release.sh - Validate state and push a semver tag for the current HEAD.
#
# The tag push triggers .github/workflows/release-publish.yaml, which retags
# the existing `<version>-<sha>` Docker images (built by ci.yml on merge to
# main) with `<version>`, `<maj.min>`, `<maj>`, and `latest`, then creates a
# GitHub Release. Nothing is rebuilt.
#
# Usage:
#   ./scripts/release.sh                  # tag HEAD with version from VERSION
#   ./scripts/release.sh --dry-run        # checks only, no tag/push
#   ./scripts/release.sh --skip-ci        # skip ci.yml success check
#   ./scripts/release.sh --skip-images    # skip DockerHub existence check
#   ./scripts/release.sh --help

set -euo pipefail

RED=$'\e[31m'
GREEN=$'\e[32m'
YELLOW=$'\e[33m'
BLUE=$'\e[34m'
BOLD=$'\e[1m'
RESET=$'\e[0m'

DRY_RUN=false
SKIP_CI=false
SKIP_IMAGES=false

usage() {
  cat <<EOF
Usage: $0 [--dry-run] [--skip-ci] [--skip-images] [-h|--help]

Validate repository state and push a semver tag (vX.Y.Z) for the current HEAD.
The version comes from the VERSION file. Downstream workflow retags pre-built
Docker images and creates a GitHub Release.

Options:
  --dry-run        Run all checks but do not create/push the tag
  --skip-ci        Skip the ci.yml "green on HEAD" check
  --skip-images    Skip the DockerHub image-existence check
  -h, --help       Show this help
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run)     DRY_RUN=true; shift ;;
    --skip-ci)     SKIP_CI=true; shift ;;
    --skip-images) SKIP_IMAGES=true; shift ;;
    -h|--help)     usage; exit 0 ;;
    *)             echo "Unknown argument: $1" >&2; usage; exit 1 ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

info() { printf '%s[•]%s %s\n' "$BLUE"   "$RESET" "$*"; }
ok()   { printf '%s[✓]%s %s\n' "$GREEN"  "$RESET" "$*"; }
warn() { printf '%s[!]%s %s\n' "$YELLOW" "$RESET" "$*"; }
err()  { printf '%s[✗]%s %s\n' "$RED"    "$RESET" "$*" >&2; }
die()  { err "$*"; exit 1; }

# ─── Git state ────────────────────────────────────────────────────────
info "Checking local git state..."

if ! git diff --quiet || ! git diff --cached --quiet; then
  die "Working tree is dirty. Commit or stash changes first."
fi
ok "Working tree clean"

BRANCH=$(git symbolic-ref --short HEAD 2>/dev/null || echo "detached")
if [ "$BRANCH" != "main" ]; then
  warn "Current branch is '$BRANCH' (not 'main')."
  read -r -p "Continue anyway? [y/N] " ans
  case "${ans:-}" in y|Y|yes) ;; *) die "Aborted." ;; esac
else
  ok "On branch main"
fi

info "Fetching from origin (including tags)..."
git fetch --quiet --tags origin main

if [ "$BRANCH" = "main" ]; then
  LOCAL=$(git rev-parse HEAD)
  REMOTE=$(git rev-parse origin/main)
  if [ "$LOCAL" != "$REMOTE" ]; then
    BEHIND=$(git rev-list --count "$LOCAL..$REMOTE")
    AHEAD=$(git rev-list --count "$REMOTE..$LOCAL")
    [ "$BEHIND" -gt 0 ] && die "Local main is $BEHIND commit(s) behind origin/main. Pull first."
    [ "$AHEAD"  -gt 0 ] && die "Local main is $AHEAD commit(s) ahead of origin/main. Push first."
  fi
  ok "Up-to-date with origin/main"
fi

# ─── Version ──────────────────────────────────────────────────────────
info "Reading VERSION..."
[ -f VERSION ] || die "VERSION file not found in $PROJECT_ROOT"
VERSION=$(tr -d '[:space:]' < VERSION)
echo "$VERSION" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$' \
  || die "VERSION content '$VERSION' is not semver X.Y.Z"
TAG="v$VERSION"
ok "Version: $VERSION → tag $TAG"

info "Verifying version sync across all files..."
if ! bash scripts/verify-version-sync.sh >/dev/null 2>&1; then
  err "verify-version-sync.sh failed. Run it directly for details:"
  err "  bash scripts/verify-version-sync.sh"
  exit 1
fi
ok "All version files synchronized"

# ─── Tag uniqueness ───────────────────────────────────────────────────
info "Checking tag $TAG does not exist..."
if git rev-parse -q --verify "refs/tags/$TAG" >/dev/null; then
  die "Tag $TAG already exists locally. Delete it or bump VERSION."
fi
if git ls-remote --tags origin "$TAG" | grep -q "refs/tags/$TAG$"; then
  die "Tag $TAG already exists on origin. Bump VERSION for a new release."
fi
ok "Tag $TAG available"

# ─── CI status ────────────────────────────────────────────────────────
HEAD_SHA=$(git rev-parse HEAD)
# Must be 7 chars to match docker/metadata-action's {{sha}} (docker-build-push.yml).
# Local git may auto-widen --short beyond 7, so pin the length explicitly.
SHORT_SHA=$(git rev-parse --short=7 HEAD)

if $SKIP_CI; then
  warn "Skipping ci.yml status check (--skip-ci)"
elif ! command -v gh >/dev/null 2>&1; then
  warn "gh CLI not installed; skipping ci.yml status check."
else
  info "Checking ci.yml status for $SHORT_SHA..."
  STATUS=$(gh run list \
    --workflow=ci.yml \
    --commit "$HEAD_SHA" \
    --limit 1 \
    --json status,conclusion \
    --jq '.[0] | "\(.status)/\(.conclusion)"' 2>/dev/null || echo "none")
  case "$STATUS" in
    "completed/success")
      ok "ci.yml green on $SHORT_SHA" ;;
    "completed/"*)
      die "ci.yml on $SHORT_SHA finished non-successfully ($STATUS). Fix before releasing." ;;
    "in_progress/"*|"queued/"*|"pending/"*)
      warn "ci.yml still running on $SHORT_SHA ($STATUS). release-publish will wait (up to 15 min)." ;;
    "none"|""|"null/null")
      warn "No ci.yml run found for $SHORT_SHA yet." ;;
    *)
      warn "Unexpected ci.yml status: $STATUS" ;;
  esac
fi

# ─── DockerHub images ─────────────────────────────────────────────────
COMPONENTS=(api worker frontend operator mcp-manager mcp-runner mcp-runner-locked events)

if $SKIP_IMAGES; then
  warn "Skipping DockerHub image check (--skip-images)"
elif ! command -v docker >/dev/null 2>&1; then
  warn "docker CLI not installed; skipping image-existence check."
else
  info "Checking DockerHub images agentarea/agentarea-*:$VERSION-$SHORT_SHA..."
  MISSING=()
  for c in "${COMPONENTS[@]}"; do
    IMG="agentarea/agentarea-$c:$VERSION-$SHORT_SHA"
    if docker buildx imagetools inspect "$IMG" >/dev/null 2>&1; then
      ok "  $IMG"
    else
      MISSING+=("$IMG")
    fi
  done
  if [ ${#MISSING[@]} -gt 0 ]; then
    warn "Missing images (${#MISSING[@]}/${#COMPONENTS[@]}):"
    for m in "${MISSING[@]}"; do warn "    $m"; done
    warn "They may still be building; release-publish retries for 15 min."
  fi
fi

# ─── Summary ──────────────────────────────────────────────────────────
PREV_TAG=$(git describe --tags --abbrev=0 --match='v*' 2>/dev/null || echo "")
COMMIT_SUBJECT=$(git log -1 --pretty=%s)

echo
printf '%s═══ Release Summary ═══%s\n' "$BOLD" "$RESET"
printf '  Tag:       %s\n' "$TAG"
printf '  Commit:    %s %s\n' "$SHORT_SHA" "$COMMIT_SUBJECT"
if [ -n "$PREV_TAG" ]; then
  COMMIT_COUNT=$(git rev-list --count "$PREV_TAG..HEAD")
  printf '  Previous:  %s (%s commits ago)\n' "$PREV_TAG" "$COMMIT_COUNT"
fi
echo
if [ -n "$PREV_TAG" ]; then
  printf '%sCommits since %s:%s\n' "$BOLD" "$PREV_TAG" "$RESET"
  git log "$PREV_TAG..HEAD" --pretty=format:'  - %s (%an)' --no-merges
  echo
fi
echo

if $DRY_RUN; then
  ok "--dry-run: exiting before tag push."
  exit 0
fi

read -r -p "Create and push tag $TAG? [y/N] " ans
case "${ans:-}" in y|Y|yes) ;; *) die "Aborted." ;; esac

# ─── Tag and push ─────────────────────────────────────────────────────
info "Creating annotated tag $TAG..."
git tag -a "$TAG" -m "Release $TAG"

info "Pushing tag to origin..."
git push origin "refs/tags/$TAG"

REPO=$(git remote get-url origin | sed -E 's#.*github\.com[:/]([^/]+/[^/.]+)(\.git)?$#\1#')
echo
ok "Tag $TAG pushed."
printf '  Workflow: https://github.com/%s/actions/workflows/release-publish.yaml\n' "$REPO"
printf '  Release:  https://github.com/%s/releases/tag/%s\n' "$REPO" "$TAG"
