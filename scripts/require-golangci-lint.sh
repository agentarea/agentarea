#!/usr/bin/env bash
# Fails unless a golangci-lint matching the pinned major.minor is on PATH.
set -euo pipefail

want=${1:?usage: require-golangci-lint.sh vX.Y.Z}
install="go install github.com/golangci/golangci-lint/v2/cmd/golangci-lint@${want}"

if ! command -v golangci-lint >/dev/null; then
  echo "golangci-lint ${want} is required. Install: ${install}" >&2
  exit 1
fi

have=$(golangci-lint version 2>/dev/null | sed -nE 's/.*version v?([0-9]+\.[0-9]+)\..*/\1/p' | head -1)
want_minor=$(echo "${want#v}" | cut -d. -f1-2)
if [ "$have" != "$want_minor" ]; then
  echo "golangci-lint ${want_minor}.x is required (CI pins ${want}), found '${have:-unknown}'. Install: ${install}" >&2
  exit 1
fi
