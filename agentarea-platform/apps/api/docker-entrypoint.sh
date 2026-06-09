#!/bin/sh
set -e

# Set PYTHONPATH to include the app package and bind-mounted workspace libraries.
# In dev, docker-compose mounts /app/libs from the host, so newly-added workspace
# packages may not exist in the image's prebuilt virtualenv until the image is
# rebuilt. Adding the source roots keeps reloads working against the mounted tree.
LIB_PATHS=""
if [ -d /app/libs ]; then
    LIB_PATHS="$(find /app/libs -mindepth 1 -maxdepth 1 -type d | paste -sd: -)"
fi

if [ -n "$LIB_PATHS" ]; then
    export PYTHONPATH="/app/apps/api:$LIB_PATHS:${PYTHONPATH:-}"
else
    export PYTHONPATH="/app/apps/api:${PYTHONPATH:-}"
fi

PYTHON_BIN="${PYTHON_BIN:-/app/.venv/bin/python}"
if [ ! -x "$PYTHON_BIN" ]; then
    PYTHON_BIN="python"
fi

# If the first argument is "agentarea-api", convert it to Python module syntax
if [ "$1" = "agentarea-api" ]; then
    shift
    exec "$PYTHON_BIN" -m agentarea_api.cli "$@"
fi

# Otherwise, execute the command as-is
exec "$@"
