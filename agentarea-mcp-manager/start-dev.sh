#!/bin/sh
set -e

echo "Initializing Podman storage..."

# Ensure storage directories exist
mkdir -p /var/lib/containers/storage
mkdir -p /run/containers/storage
mkdir -p /tmp/containers

# Reset and initialize Podman storage
podman system migrate 2>/dev/null || true
podman system info > /dev/null 2>&1 || {
    echo "Initializing Podman system..."
    # Clean up any corrupted state
    rm -rf /var/lib/containers/storage/libpod 2>/dev/null || true
    rm -rf /var/lib/containers/storage/overlay-* 2>/dev/null || true
}

# Create Podman network if it doesn't exist
podman network exists podman 2>/dev/null || podman network create podman 2>/dev/null || true

echo "Podman initialization complete"
podman info --format "Storage Driver: {{.Store.GraphDriverName}}" || echo "Warning: Could not get podman info"

# Check if we're in development mode with source code mounted
if [ -f "/app/cmd/mcp-manager/main.go" ]; then
    echo "Development mode detected: source code is mounted"

    # If tmp/main exists (pre-built), run it directly
    if [ -f "/app/tmp/main" ]; then
        echo "Found pre-built binary at /app/tmp/main, running..."
        exec /app/tmp/main
    fi

    # Otherwise, try to build and run
    echo "No pre-built binary found. Building..."
    cd /app && go build -o ./tmp/main ./cmd/mcp-manager
    exec /app/tmp/main
else
    # Production mode - use the built binary
    echo "Production mode: using built binary"
    exec /app/mcp-manager
fi
