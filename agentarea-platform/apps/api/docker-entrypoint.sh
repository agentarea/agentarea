#!/bin/sh
set -e

# Set PYTHONPATH to include the apps/api directory so Python can find agentarea_api module
export PYTHONPATH="/app/apps/api:${PYTHONPATH:-}"

# If the first argument is "agentarea-api", convert it to Python module syntax
if [ "$1" = "agentarea-api" ]; then
    shift
    exec python -m agentarea_api.cli "$@"
fi

# Otherwise, execute the command as-is
exec "$@"

