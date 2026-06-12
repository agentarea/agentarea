#!/bin/sh
set -e

# Fallback dev entrypoint used when Air is unavailable. The manager drives MCP
# containers through the mounted Docker socket, so there is no runtime to init.

if [ -f "/app/cmd/mcp-manager/main.go" ]; then
    echo "Development mode detected: source code is mounted"

    # If tmp/main exists (pre-built), run it directly
    if [ -f "/app/tmp/main" ]; then
        echo "Found pre-built binary at /app/tmp/main, running..."
        exec /app/tmp/main
    fi

    # Otherwise, build and run
    echo "No pre-built binary found. Building..."
    cd /app && go build -o ./tmp/main ./cmd/mcp-manager
    exec /app/tmp/main
else
    # Production binary already built into the image
    echo "Production mode: using built binary"
    exec /app/mcp-manager
fi
