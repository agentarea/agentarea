# Build stage
FROM python:3.12-slim as builder

WORKDIR /app

# Install uv
RUN pip install uv

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

# Install curl for healthchecks and security updates
RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y curl && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder
COPY --from=builder --chown=appuser:appuser /app/.venv /app/.venv

# Copy project files with correct ownership
COPY --chown=appuser:appuser libs ./libs
COPY --chown=appuser:appuser apps/api ./apps/api
COPY --chown=appuser:appuser apps/api/alembic.ini ./alembic.ini
COPY --chown=appuser:appuser apps/api/alembic ./alembic
COPY --chown=appuser:appuser apps/api/agentarea_api/cli.py ./
COPY --chown=appuser:appuser apps/api/docker-entrypoint.sh ./docker-entrypoint.sh
COPY --chown=appuser:appuser pyproject.toml ./

# Make entrypoint executable (small operation, minimal layer impact)
RUN chmod +x /app/docker-entrypoint.sh

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PATH="/app/.venv/bin:$PATH"

# Switch to non-root user
USER appuser

# Define healthcheck
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

EXPOSE 8000

# Stay in root directory where cli.py is located
WORKDIR /app

# Set entrypoint to handle agentarea-api command conversion
ENTRYPOINT ["/app/docker-entrypoint.sh"]

# Default command: serve the API
CMD ["agentarea-api", "serve"] 