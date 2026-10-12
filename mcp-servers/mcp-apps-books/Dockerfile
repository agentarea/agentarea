# Runtime image only: `bun run build` produces dist/server.js (all server
# dependencies and the demo dataset bundled) and dist/app/*.html (one
# single-file bundle per view). The server runs on Bun for bun:sqlite.
#
# State lives in the instance's MCP storage, never in the container: it needs
# MCP_MANAGER_URL, MCP_INSTANCE_ID and MCP_STORAGE_TOKEN, and writes the
# demo books into a new database only with AGENTAREA_MCP_SEED_DEMO=1.
FROM oven/bun:1.3.14-slim

WORKDIR /app
COPY dist/server.js dist/server.js
COPY dist/app/ dist/app/

# AgentArea runs docker-type MCP connections on container port 8000.
ENV MCP_HOST=0.0.0.0 \
    MCP_PORT=8000

EXPOSE 8000
USER bun
CMD ["bun", "dist/server.js"]
