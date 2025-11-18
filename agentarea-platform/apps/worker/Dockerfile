# Build stage
FROM python:3.12-slim as builder

WORKDIR /app

# Install uv via official installer
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*
RUN curl -LsSf https://astral.sh/uv/install.sh | sh && ln -sf /root/.local/bin/uv /usr/local/bin/uv

# Copy workspace configuration and source
COPY pyproject.toml uv.lock ./
COPY README.md ./
COPY libs/ ./libs/
COPY apps/ ./apps/

# Use uv to install dependencies and project packages (exclude dev and test dependencies)
# --all-packages ensures workspace packages and their dependencies are installed
RUN uv sync --frozen --no-dev --no-group test --all-packages

# Runtime stage
FROM python:3.12-slim

# Create a non-root user to run the application
RUN groupadd -r appuser && useradd -r -g appuser -d /app appuser

WORKDIR /app

# Install security updates
RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder
COPY --from=builder --chown=appuser:appuser /app/.venv /app/.venv

# Copy project files with correct ownership
COPY --chown=appuser:appuser libs ./libs
COPY --chown=appuser:appuser apps/worker ./apps/worker
COPY --chown=appuser:appuser apps/worker/docker-entrypoint.sh ./docker-entrypoint.sh
COPY --chown=appuser:appuser pyproject.toml ./

# Make entrypoint executable (small operation, minimal layer impact)
RUN chmod +x /app/docker-entrypoint.sh

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PATH="/app/.venv/bin:$PATH"

# Switch to non-root user
USER appuser

# Stay in root directory
WORKDIR /app

# Set entrypoint to handle agentarea-worker command conversion
ENTRYPOINT ["/app/docker-entrypoint.sh"]

# Default command: start the worker
CMD ["agentarea-worker", "start"] 
