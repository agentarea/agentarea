#!/bin/bash
# get-version.sh - Read version from VERSION file
# Usage:
#   ./scripts/get-version.sh           # Returns: 0.0.3
#   ./scripts/get-version.sh --tag     # Returns: v0.0.3
#   ./scripts/get-version.sh --dev     # Returns: 0.0.3-dev.abc1234

set -euo pipefail

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
VERSION_FILE="$PROJECT_ROOT/VERSION"

# Read base version
if [ ! -f "$VERSION_FILE" ]; then
  echo "ERROR: VERSION file not found at $VERSION_FILE" >&2
  exit 1
fi

BASE_VERSION=$(cat "$VERSION_FILE" | tr -d '[:space:]')

if [ -z "$BASE_VERSION" ]; then
  echo "ERROR: VERSION file is empty" >&2
  exit 1
fi

# Parse arguments
MODE="${1:-plain}"

case "$MODE" in
  --tag)
    echo "v${BASE_VERSION}"
    ;;
  --dev)
    SHORT_SHA="${GITHUB_SHA::7}"
    if [ -z "${GITHUB_SHA:-}" ]; then
      SHORT_SHA=$(git rev-parse --short=7 HEAD 2>/dev/null || echo "dev")
    fi
    echo "${BASE_VERSION}-dev.${SHORT_SHA}"
    ;;
  --plain|*)
    echo "${BASE_VERSION}"
    ;;
esac
