# Build stage
FROM python:3.14.8-slim-trixie AS builder

WORKDIR /app

# uv, pinned by digest. The previous `curl -LsSf https://astral.sh/uv/install.sh | sh`
# installed whichever uv had shipped that morning, so a production image could not be
# rebuilt to the same bytes and a bad uv release would land in prod unreviewed. The
# digest also removes the network installer, and with it the reason this stage needed
# curl at all. Bump together with required-version in pyproject.toml.
COPY --from=ghcr.io/astral-sh/uv:0.13.3@sha256:bee0a2a458fd956c5df7b8b4c5fed2257b0af34866e3da7b51db0be3acb375d1 /uv /uvx /bin/

# Copy workspace configuration and source
COPY pyproject.toml uv.lock ./
COPY README.md ./
COPY libs/ ./libs/
COPY apps/ ./apps/

# Use uv to install dependencies and project packages (exclude dev and test dependencies)
# --all-packages ensures workspace packages and their dependencies are installed
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-group test --all-packages --compile-bytecode

# The token counter's encoding ships in the image, never fetched at run time.
RUN TIKTOKEN_CACHE_DIR=/app/.tiktoken /app/.venv/bin/python -c "import tiktoken; tiktoken.get_encoding('o200k_base')"

# Runtime stage
FROM python:3.14.8-slim-trixie

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
COPY --from=builder --chown=appuser:appuser /app/.tiktoken /app/.tiktoken

# Copy project files with correct ownership
COPY --chown=appuser:appuser libs ./libs
COPY --chown=appuser:appuser apps/api ./apps/api
COPY --chown=appuser:appuser apps/worker ./apps/worker
COPY --chown=appuser:appuser apps/worker/docker-entrypoint.sh ./docker-entrypoint.sh
COPY --chown=appuser:appuser pyproject.toml ./

# Make entrypoint executable (small operation, minimal layer impact)
RUN chmod 755 /app/docker-entrypoint.sh && \
    python -m compileall -q -j0 /app/apps /app/libs && \
    chmod -R a+rX /app/apps /app/libs

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV TIKTOKEN_CACHE_DIR=/app/.tiktoken
ENV PATH="/app/.venv/bin:$PATH"

# Switch to non-root user
USER appuser

# Stay in root directory
WORKDIR /app

# Set entrypoint to handle agentarea-worker command conversion
ENTRYPOINT ["/app/docker-entrypoint.sh"]

# Default command: start the worker
CMD ["agentarea-worker", "start"] 
