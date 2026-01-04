#!/bin/bash
# verify-version-sync.sh - Verify all version files match VERSION file
# Used in CI to catch desynchronization
# NOTE: Chart.yaml 'version' field is NOT checked (independent versioning)

set -euo pipefail

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

EXPECTED_VERSION=$(cat "$PROJECT_ROOT/VERSION" | tr -d '[:space:]')
ERRORS=0

echo "Verifying all versions match VERSION file: $EXPECTED_VERSION"
echo "=================================================="

# Check bumpversion config
BUMPVERSION_VERSION=$(grep "^current_version:" "$PROJECT_ROOT/.bumpversion.yaml" | sed 's/current_version: //' | tr -d '[:space:]')
if [ "$BUMPVERSION_VERSION" != "$EXPECTED_VERSION" ]; then
  echo "❌ .bumpversion.yaml current_version: $BUMPVERSION_VERSION (expected: $EXPECTED_VERSION)"
  ERRORS=$((ERRORS + 1))
else
  echo "✅ .bumpversion.yaml: $BUMPVERSION_VERSION"
fi

# Check Chart.yaml appVersion (NOT version - that's independent)
CHART_APP_VERSION=$(grep "^appVersion:" "$PROJECT_ROOT/charts/agentarea/Chart.yaml" | sed 's/appVersion: //' | tr -d '"' | tr -d '[:space:]')
if [ "$CHART_APP_VERSION" != "$EXPECTED_VERSION" ]; then
  echo "❌ Chart.yaml appVersion: $CHART_APP_VERSION (expected: $EXPECTED_VERSION)"
  ERRORS=$((ERRORS + 1))
else
  echo "✅ Chart.yaml appVersion: $CHART_APP_VERSION"
fi

# Check pyproject.toml files (exclude node_modules and .venv)
while IFS= read -r file; do
  # Skip if in node_modules or .venv
  if [[ "$file" == *"node_modules"* ]] || [[ "$file" == *".venv"* ]]; then
    continue
  fi

  PYPROJECT_VERSION=$(grep '^version = ' "$file" | head -1 | sed 's/version = "\(.*\)"/\1/')
  if [ "$PYPROJECT_VERSION" != "$EXPECTED_VERSION" ]; then
    REL_PATH=$(realpath --relative-to="$PROJECT_ROOT" "$file" 2>/dev/null || echo "$file")
    echo "❌ $REL_PATH: $PYPROJECT_VERSION (expected: $EXPECTED_VERSION)"
    ERRORS=$((ERRORS + 1))
  fi
done < <(find "$PROJECT_ROOT" -name "pyproject.toml" -type f)

# Check package.json
PACKAGE_JSON="$PROJECT_ROOT/agentarea-webapp/package.json"
if [ -f "$PACKAGE_JSON" ]; then
  PACKAGE_VERSION=$(grep '"version":' "$PACKAGE_JSON" | sed 's/.*"version": "\(.*\)".*/\1/')
  if [ "$PACKAGE_VERSION" != "$EXPECTED_VERSION" ]; then
    echo "❌ agentarea-webapp/package.json: $PACKAGE_VERSION (expected: $EXPECTED_VERSION)"
    ERRORS=$((ERRORS + 1))
  else
    echo "✅ agentarea-webapp/package.json: $PACKAGE_VERSION"
  fi
fi

echo "=================================================="
if [ $ERRORS -eq 0 ]; then
  echo "✅ All versions synchronized to $EXPECTED_VERSION"
  echo ""
  echo "Note: Chart version (charts/agentarea/Chart.yaml 'version' field) is"
  echo "managed independently and is NOT checked by this script."
  exit 0
else
  echo "❌ Found $ERRORS version mismatches"
  echo ""
  echo "To fix: Run 'python3 scripts/sync-versions.py' to synchronize all versions"
  exit 1
fi
