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

# Start the MCP Manager
exec /app/mcp-manager