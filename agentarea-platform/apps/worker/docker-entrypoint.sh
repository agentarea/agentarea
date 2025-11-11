#!/bin/sh
set -e

# Set PYTHONPATH to include the apps/worker directory so Python can find agentarea_worker module
export PYTHONPATH="/app/apps/worker:${PYTHONPATH:-}"

# If the first argument is "agentarea-worker", convert it to Python module syntax
if [ "$1" = "agentarea-worker" ]; then
    shift
    exec python -m agentarea_worker.cli "$@"
fi

# Otherwise, execute the command as-is
exec "$@"

