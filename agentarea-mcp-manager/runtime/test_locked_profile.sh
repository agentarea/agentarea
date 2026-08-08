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

# PATH absence is not enough: `node /usr/lib/node_modules/npm/bin/npm-cli.js`
# installs packages without ever consulting PATH, so the module trees the image
# deletes have to be gone too.
for tree in /usr/lib/node_modules/npm /usr/lib/node_modules/corepack \
            /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/corepack; do
    if [ -e "$tree" ]; then
        fail "$tree remains installed"
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
