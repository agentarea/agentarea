# syntax=docker/dockerfile:1

# ---- Build stage ----
FROM golang:1.25-alpine AS builder

RUN apk add --no-cache git ca-certificates

WORKDIR /app

# Cache dependencies
COPY go.mod go.sum ./
RUN go mod download

# Build both binaries for the target architecture.
# -ldflags="-s -w" strips debug symbols + DWARF (~30% smaller, no runtime impact).
COPY . .
ARG TARGETARCH
ARG TARGETOS
RUN CGO_ENABLED=0 GOOS=${TARGETOS:-linux} GOARCH=${TARGETARCH} go build -ldflags="-s -w" -installsuffix cgo -o bin/mcp-manager ./cmd/mcp-manager \
    && CGO_ENABLED=0 GOOS=${TARGETOS:-linux} GOARCH=${TARGETARCH} go build -ldflags="-s -w" -installsuffix cgo -o bin/sandbox-runner ./cmd/sandbox-runner

# ---- Development stage (hot reload via Air) ----
# Same docker-CLI runtime model as production, plus the Go toolchain + Air so a
# bind-mounted source tree rebuilds on change. Opt-in only: build with
# `--target dev` (docker-compose.dev.yaml does this). It is deliberately NOT the
# last stage so a plain `docker build` / CI build without --target never ships
# this image (it has no compiled binary and crash-loops in a pod).
FROM golang:1.25-alpine AS dev

RUN apk add --no-cache git ca-certificates docker-cli dumb-init \
    && rm -rf /var/cache/apk/*

RUN go install github.com/air-verse/air@latest

WORKDIR /app

# Pre-cache dependencies so the first reload is fast
COPY go.mod go.sum ./
RUN go mod download

EXPOSE 8000 80

ENTRYPOINT ["/usr/bin/dumb-init", "--"]
CMD ["sh", "-c", "if [ -f /app/.air.toml ] && command -v air >/dev/null 2>&1; then exec air -c /app/.air.toml; else exec /app/start-dev.sh; fi"]

# ---- Production stage ----
# MUST be the LAST stage: buildx builds the final stage when no --target is
# given, so this is what CI publishes by default.
# Slim runtime: ships only the docker CLI so the manager can drive containers
# through the mounted Docker socket. No podman/buildah/skopeo, no privileged mode.
FROM alpine:3.20 AS production

RUN apk add --no-cache ca-certificates docker-cli dumb-init \
    && rm -rf /var/cache/apk/*

WORKDIR /app

COPY --from=builder /app/bin/mcp-manager /app/mcp-manager
COPY --from=builder /app/bin/sandbox-runner /app/sandbox-runner

# Templates are mounted at runtime
RUN mkdir -p /app/templates

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD /app/mcp-manager --health || exit 1

# 8000: mcp-manager API, 80: internal proxy
EXPOSE 8000 80

ENTRYPOINT ["/usr/bin/dumb-init", "--"]
CMD ["/app/mcp-manager"]
