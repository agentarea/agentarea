#!/usr/bin/env bash
# validate.sh — Run lint + tests for selected modules (or all)
#
# Usage:
#   ./scripts/validate.sh                  # validate everything
#   ./scripts/validate.sh platform         # Python lint + tests only
#   ./scripts/validate.sh mcp-manager      # Go build + vet only
#   ./scripts/validate.sh webapp           # Next.js type-check + lint
#   ./scripts/validate.sh platform mcp-manager  # multiple modules
#
# Options:
#   --lint-only    Skip tests, run only linting/type-checking
#   --test-only    Skip linting, run only tests
#   --fix          Auto-fix lint issues where possible

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
MODULES=()
LINT_ONLY=false
TEST_ONLY=false
FIX=false
FAILED=()
PASSED=()

# Parse arguments
for arg in "$@"; do
    case "$arg" in
        --lint-only) LINT_ONLY=true ;;
        --test-only) TEST_ONLY=true ;;
        --fix) FIX=true ;;
        *) MODULES+=("$arg") ;;
    esac
done

# Default: all modules
if [ ${#MODULES[@]} -eq 0 ]; then
    MODULES=(platform mcp-manager webapp)
fi

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

step() { echo -e "\n${BLUE}▸ $1${NC}"; }
pass() { echo -e "  ${GREEN}✓ $1${NC}"; PASSED+=("$1"); }
fail() { echo -e "  ${RED}✗ $1${NC}"; FAILED+=("$1"); }
skip() { echo -e "  ${YELLOW}⊘ $1 (skipped)${NC}"; }

# ─── Python Platform ───────────────────────────────────────────────
validate_platform() {
    local dir="$ROOT_DIR/agentarea-platform"
    if [ ! -d "$dir" ]; then
        fail "platform: directory not found"
        return
    fi

    step "Python Platform"

    if [ "$TEST_ONLY" != "true" ]; then
        if [ "$FIX" = "true" ]; then
            step "  Formatting (ruff format + fix)"
            if (cd "$dir" && uv run ruff format && uv run ruff check --fix) 2>&1; then
                pass "platform:format"
            else
                fail "platform:format"
            fi
        fi

        step "  Linting (ruff check)"
        if (cd "$dir" && uv run ruff check) 2>&1; then
            pass "platform:lint"
        else
            fail "platform:lint"
        fi
    fi

    if [ "$LINT_ONLY" != "true" ]; then
        step "  Tests (pytest)"
        if (cd "$dir" && uv run python -m pytest tests/unit tests/functional apps/api/tests libs/common/tests libs/tasks/tests -m "not integration" -q) 2>&1; then
            pass "platform:test"
        else
            fail "platform:test"
        fi
    fi
}

# ─── Go MCP Manager ───────────────────────────────────────────────
validate_mcp_manager() {
    local dir="$ROOT_DIR/agentarea-mcp-manager"
    if [ ! -d "$dir" ]; then
        fail "mcp-manager: directory not found"
        return
    fi

    step "Go MCP Manager"

    if [ "$TEST_ONLY" != "true" ]; then
        step "  Build"
        if (cd "$dir" && go build ./...) 2>&1; then
            pass "mcp-manager:build"
        else
            fail "mcp-manager:build"
        fi

        step "  Vet"
        if (cd "$dir" && go vet ./...) 2>&1; then
            pass "mcp-manager:vet"
        else
            fail "mcp-manager:vet"
        fi
    fi

    if [ "$LINT_ONLY" != "true" ]; then
        step "  Tests"
        if (cd "$dir" && go test ./... -short) 2>&1; then
            pass "mcp-manager:test"
        else
            fail "mcp-manager:test"
        fi
    fi
}

# ─── Next.js Webapp ───────────────────────────────────────────────
validate_webapp() {
    local dir="$ROOT_DIR/agentarea-webapp"
    if [ ! -d "$dir" ]; then
        fail "webapp: directory not found"
        return
    fi

    step "Next.js Webapp"

    if [ "$TEST_ONLY" != "true" ]; then
        step "  Type-check (tsc)"
        if (cd "$dir" && npx tsc --noEmit) 2>&1; then
            pass "webapp:typecheck"
        else
            fail "webapp:typecheck"
        fi

        step "  Lint (next lint)"
        if (cd "$dir" && npx next lint) 2>&1; then
            pass "webapp:lint"
        else
            fail "webapp:lint"
        fi
    fi
}

# ─── Run selected modules ─────────────────────────────────────────
for module in "${MODULES[@]}"; do
    case "$module" in
        platform)     validate_platform ;;
        mcp-manager)  validate_mcp_manager ;;
        webapp)       validate_webapp ;;
        *)
            echo -e "${RED}Unknown module: $module${NC}"
            echo "Available: platform, mcp-manager, webapp"
            exit 1
            ;;
    esac
done

# ─── Summary ──────────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [ ${#PASSED[@]} -gt 0 ]; then
    echo -e "${GREEN}Passed (${#PASSED[@]}):${NC}"
    for p in "${PASSED[@]}"; do echo -e "  ${GREEN}✓${NC} $p"; done
fi
if [ ${#FAILED[@]} -gt 0 ]; then
    echo -e "${RED}Failed (${#FAILED[@]}):${NC}"
    for f in "${FAILED[@]}"; do echo -e "  ${RED}✗${NC} $f"; done
    echo ""
    exit 1
fi
echo -e "${GREEN}All checks passed!${NC}"
