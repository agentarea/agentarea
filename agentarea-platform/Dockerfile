# syntax=docker/dockerfile:1
#
# The open-core binary: `agentarea <role>` (serve, worker, events, mcp, all,
# migrate, ...). Static, CGO off; icons, migrations and the authz model are
# embedded. The runtime carries CA roots, tzdata (cron and schedule time
# zones) and the docker CLI, which the docker MCP backend drives through a
# mounted socket. On Kubernetes the backend is the API, and the CLI is unused.
#
# GO_IMAGE and RUNTIME_IMAGE exist so a build can name images already present
# locally; GOTOOLCHAIN=auto lets an older Go image fetch the go.mod toolchain.
ARG GO_IMAGE=golang:1.27.4-alpine3.24
ARG RUNTIME_IMAGE=alpine:3.24.4

FROM ${GO_IMAGE} AS builder
ENV CGO_ENABLED=0 GOTOOLCHAIN=auto GOFLAGS=-mod=readonly
WORKDIR /src
COPY go.mod go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod go mod download
COPY . .
ARG TARGETOS
ARG TARGETARCH
RUN --mount=type=cache,target=/go/pkg/mod --mount=type=cache,target=/root/.cache/go-build \
    GOOS=${TARGETOS:-linux} GOARCH=${TARGETARCH} \
    go build -trimpath -ldflags="-s -w" -o /out/agentarea ./cmd/agentarea

# The development stack's hot-reload image (docker-compose.dev.yaml `app`): the
# Go toolchain and air, which rebuild and restart `agentarea` from the mounted
# source (.air.toml). Not a release image; the default target stays the last stage.
FROM ${GO_IMAGE} AS dev
ENV CGO_ENABLED=0 GOTOOLCHAIN=auto GOFLAGS=-mod=readonly
RUN apk add --no-cache ca-certificates tzdata docker-cli
RUN --mount=type=cache,target=/go/pkg/mod --mount=type=cache,target=/root/.cache/go-build \
    go install github.com/air-verse/air@v1.67.4
WORKDIR /src
ENTRYPOINT ["air", "-c", "/src/agentarea/agentarea-platform/.air.toml"]

FROM ${RUNTIME_IMAGE}
RUN apk upgrade --no-cache \
    && apk add --no-cache ca-certificates tzdata docker-cli \
    && adduser -D -H -u 10001 agentarea
COPY --from=builder /out/agentarea /usr/local/bin/agentarea
# Non-root by default; a container that drives a mounted docker socket runs
# with the socket's group or as root, set by the deployment.
USER 10001
EXPOSE 8000
ENTRYPOINT ["/usr/local/bin/agentarea"]
CMD ["serve"]
