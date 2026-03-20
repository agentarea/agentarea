#!/usr/bin/env bash
# Download registry data from remote sources into agentarea-bootstrap/data/registries/
# Usage: ./scripts/sync-registries.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REGISTRIES_DIR="$ROOT_DIR/agentarea-bootstrap/data/registries"

# Registry sources
MCP_REGISTRY_URL="${MCP_REGISTRY_URL:-https://agentarea-mcp-registry.s3.amazonaws.com/registry/mcp-servers.json}"

BLUE='\033[0;34m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'

mkdir -p "$REGISTRIES_DIR"

echo -e "${BLUE}Syncing registries to $REGISTRIES_DIR${NC}"

# MCP Servers Registry
echo -e "${YELLOW}Downloading MCP servers registry...${NC}"
if curl -fSL --connect-timeout 30 --max-time 120 \
  -H "Accept: application/json" \
  -o "$REGISTRIES_DIR/mcp-servers.json" \
  "$MCP_REGISTRY_URL"; then
  COUNT=$(python3 -c "import json; d=json.load(open('$REGISTRIES_DIR/mcp-servers.json')); print(len(d.get('servers', [])))" 2>/dev/null || echo "?")
  echo -e "${GREEN}  Downloaded MCP registry ($COUNT servers)${NC}"
else
  echo -e "${YELLOW}  Failed to download MCP registry — will use S3 fallback at bootstrap${NC}"
fi

# Add more registries here as needed:
# echo -e "${YELLOW}Downloading skills registry...${NC}"
# curl -fSL -o "$REGISTRIES_DIR/skills.yaml" "$SKILLS_REGISTRY_URL"

echo -e "${GREEN}Registry sync complete!${NC}"
