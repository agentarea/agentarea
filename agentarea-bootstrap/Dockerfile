# Build stage
FROM python:3.12-slim as builder

WORKDIR /app

# Install uv via official installer
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*
RUN curl -LsSf https://astral.sh/uv/install.sh | sh && ln -sf /root/.local/bin/uv /usr/local/bin/uv

# Copy project files
COPY pyproject.toml uv.lock ./
COPY code/ ./code/
COPY main.py ./

# Use uv to install dependencies (exclude dev dependencies)
RUN uv sync --frozen --no-dev

# Runtime stage
FROM python:3.12-slim

# Create a non-root user to run the application
RUN groupadd -r appuser && useradd -r -g appuser -d /app appuser

WORKDIR /app

# Install system dependencies including MinIO client
RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y curl wget && \
    # Install MinIO client
    wget https://dl.min.io/client/mc/release/linux-amd64/mc && \
    chmod +x mc && \
    mv mc /usr/local/bin/ && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder
COPY --from=builder --chown=appuser:appuser /app/.venv /app/.venv

# Copy project files with correct ownership
COPY --chown=appuser:appuser code/ ./code/
COPY --chown=appuser:appuser main.py ./
COPY --chown=appuser:appuser data/ ./llm/

# Set environment variables
ENV PYTHONPATH=/app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PATH="/app/.venv/bin:$PATH"

# Switch to non-root user
USER appuser

# Default command to run the bootstrap
CMD ["python", "main.py"]