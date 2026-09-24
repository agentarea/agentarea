# Runtime image only: `bun run build` produces dist/server.js (all server
# dependencies bundled) and dist/app/dashboard.html (the single-file view).
# The dataset is bound at start through DATA_PATH; it ships here as the default.
FROM node:22-slim

WORKDIR /app
COPY dist/server.js dist/server.js
COPY dist/app/dashboard.html dist/app/dashboard.html
# The server writes mutations back next to the file (temp file + rename).
RUN mkdir /data && chown node:node /data
COPY --chown=node:node data/outreach.json /data/outreach.json

# AgentArea runs docker-type MCP connections on container port 8000.
ENV MCP_HOST=0.0.0.0 \
    MCP_PORT=8000 \
    DATA_PATH=/data/outreach.json

EXPOSE 8000
USER node
CMD ["node", "dist/server.js"]
