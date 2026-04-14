# Build stage
FROM golang:1.25-alpine AS builder

RUN apk add --no-cache git ca-certificates

WORKDIR /app

COPY go.mod go.sum ./
RUN go mod download

COPY . .

ARG TARGETARCH
ARG TARGETOS
RUN CGO_ENABLED=0 GOOS=${TARGETOS:-linux} GOARCH=${TARGETARCH} go build -installsuffix cgo -o bin/event-service ./cmd/server

# Runtime stage
FROM alpine:3.20

RUN apk add --no-cache ca-certificates dumb-init && rm -rf /var/cache/apk/*

RUN adduser -D -u 1000 appuser

WORKDIR /app

COPY --from=builder /app/bin/event-service /app/event-service

USER appuser

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD pgrep event-service || exit 1

ENTRYPOINT ["/usr/bin/dumb-init", "--"]
CMD ["/app/event-service"]
