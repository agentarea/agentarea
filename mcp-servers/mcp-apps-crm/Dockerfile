# Build context is mcp-servers/: the app imports the shared kit from
# ../mcp-apps-kit. `bun run build` produces dist/server.js (all server
# dependencies and the demo dataset bundled) and dist/app/*.html (one
# single-file bundle per view). The server runs on Bun for bun:sqlite.
#
# State lives in the instance's MCP storage, never in the container: it needs
# MCP_MANAGER_URL, MCP_INSTANCE_ID and MCP_STORAGE_TOKEN, and writes the
# demo CRM into a new database only with AGENTAREA_MCP_SEED_DEMO=1.
FROM oven/bun:1.4.3-slim AS build

WORKDIR /src/mcp-apps-crm
COPY mcp-apps-crm/package.json mcp-apps-crm/bun.lock ./
RUN bun install --frozen-lockfile
COPY mcp-apps-kit/ /src/mcp-apps-kit/
COPY mcp-apps-crm/ ./
RUN bun run build

FROM oven/bun:1.4.3-slim

WORKDIR /app
COPY --from=build /src/mcp-apps-crm/dist/server.js dist/server.js
COPY --from=build /src/mcp-apps-crm/dist/app/ dist/app/

# AgentArea runs docker-type MCP connections on container port 8000.
ENV MCP_HOST=0.0.0.0 \
    MCP_PORT=8000

EXPOSE 8000
USER bun
CMD ["bun", "dist/server.js"]
