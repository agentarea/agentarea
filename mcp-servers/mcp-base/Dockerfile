# mcp-base: the runtime image for MCP servers AgentArea runs from packages.
#
#   python -m mcp_base <command> [args...]
#
# runs a stdio MCP server (`npx -y <pkg>`, `uvx <pkg>`, or a command baked into
# an image built FROM this one) behind a bridge that serves Streamable HTTP on
# $PORT at /mcp for protocol 2026-07-28 and 2025 clients.
FROM node:22-bookworm-slim AS node
FROM ghcr.io/astral-sh/uv:0.8.22 AS uv

FROM python:3.12-slim-bookworm

COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx
COPY --from=uv /uv /uvx /usr/local/bin/

# git for git-sourced npm/uvx packages.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

# The TypeScript MCP SDKs, pinned, for MCP App layers built on this image:
# an app links them instead of shipping its own copy.
COPY sdk/package.json sdk/package-lock.json /opt/mcp-base/node/
RUN cd /opt/mcp-base/node && npm ci --omit=dev --no-audit --no-fund && npm cache clean --force

# The bridge lives in its own venv, off PATH, so the servers it starts see the
# system Python and none of the bridge's packages. Bytecode is compiled at
# build time: the venv is read-only for the runtime user, and recompiling the
# SDK on every cold start costs seconds.
COPY requirements.txt /opt/mcp-base/requirements.txt
RUN uv venv /opt/mcp-base/venv \
    && uv pip install --no-cache --compile-bytecode --python /opt/mcp-base/venv/bin/python -r /opt/mcp-base/requirements.txt
COPY mcp_base /opt/mcp-base/venv/lib/python3.12/site-packages/mcp_base
RUN /opt/mcp-base/venv/bin/python -m compileall -q /opt/mcp-base/venv/lib/python3.12/site-packages/mcp_base

# Matches the manager's default isolation user.
RUN useradd --uid 10001 --home-dir /tmp --no-create-home mcp
USER mcp

ENV PYTHONUNBUFFERED=1 \
    PORT=8080 \
    HOME=/tmp \
    NPM_CONFIG_CACHE=/tmp/.npm-cache \
    NPM_CONFIG_UPDATE_NOTIFIER=false \
    UV_CACHE_DIR=/tmp/.uv-cache
EXPOSE 8080

ENTRYPOINT ["/opt/mcp-base/venv/bin/python", "-m", "mcp_base"]
