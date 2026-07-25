#!/bin/sh
set -eu

fail() {
    echo "locked runtime invariant failed: $1" >&2
    exit 1
}

for command in pip pip3 pip3.12 npm npx corepack yarn pnpm; do
    if command -v "$command" >/dev/null 2>&1; then
        fail "$command remains on PATH"
    fi
done

if python -m pip --version >/dev/null 2>&1; then
    fail "python -m pip remains available"
fi
if python -m ensurepip --version >/dev/null 2>&1; then
    fail "python -m ensurepip can restore pip"
fi

probe="$(mktemp -d)"
trap 'rm -rf "$probe"' EXIT
if python -m venv "$probe/venv" >/dev/null 2>&1; then
    fail "python -m venv can create a package-manager environment"
fi

if find /opt/runtime/venv \( -type f -o -type d \) -perm /022 -print -quit | grep -q .; then
    fail "managed virtual environment is writable by non-root users"
fi
