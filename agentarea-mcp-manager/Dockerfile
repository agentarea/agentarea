# Build stage
FROM golang:1.25-alpine AS builder

# Install build dependencies
RUN apk add --no-cache git ca-certificates

# Set working directory
WORKDIR /app

# Copy go.mod and go.sum
COPY go.mod go.sum ./

# Download dependencies
RUN go mod download

# Copy source code
COPY . .

# Build the application for target architecture
ARG TARGETARCH
ARG TARGETOS
RUN CGO_ENABLED=0 GOOS=${TARGETOS:-linux} GOARCH=${TARGETARCH} go build -installsuffix cgo -o bin/mcp-manager ./cmd/mcp-manager

# Runtime stage
FROM alpine:3.20

# Install runtime dependencies including Podman
RUN apk add --no-cache \
    ca-certificates \
    curl \
    podman \
    buildah \
    skopeo \
    fuse-overlayfs \
    shadow \
    dumb-init \
    iptables \
    && rm -rf /var/cache/apk/*

# Configure Podman
RUN mkdir -p /etc/containers \
    && printf '[registries.search]\nregistries = ["docker.io", "quay.io"]\n' > /etc/containers/registries.conf \
    && printf '[storage]\ndriver = "overlay"\nrunroot = "/tmp/containers"\ngraphroot = "/var/lib/containers/storage"\n\n[storage.options]\nmount_program = "/usr/bin/fuse-overlayfs"\n' > /etc/containers/storage.conf \
    && printf '[engine]\nlock_type="file"\n\n[containers]\n' > /etc/containers/containers.conf

# Create non-root user for Podman
RUN adduser -D -u 1000 -g users -s /bin/sh podman-user \
    && mkdir -p /home/podman-user/.local/share/containers \
    && chown -R podman-user:users /home/podman-user/.local \
    && echo "podman-user:100000:65536" > /etc/subuid \
    && echo "podman-user:100000:65536" > /etc/subgid

# Set working directory
WORKDIR /app

# Copy binary from builder stage
COPY --from=builder /app/bin/mcp-manager /app/mcp-manager

# Copy startup script
COPY start-go.sh /app/start.sh
RUN chmod +x /app/start.sh

# Copy templates directory structure (will be mounted)
RUN mkdir -p /app/templates

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD /app/mcp-manager --health || exit 1

# Expose port
EXPOSE 8000

# Switch to non-root user for setup
USER podman-user

# Initialize Podman for the user
RUN podman system migrate 2>/dev/null || true

# Switch back to root to run the service (needed for container management)
USER root

# Use dumb-init for proper signal handling
ENTRYPOINT ["/usr/bin/dumb-init", "--"]

# Run the application via startup script (initializes Podman first)
CMD ["/bin/sh", "/app/start.sh"]