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
COPY README.md ./

# Use uv to install dependencies (exclude dev dependencies)
RUN uv sync --no-dev 

# Runtime stage
FROM python:3.12-slim

# Create a non-root user to run the application
RUN groupadd -r appuser && useradd -r -g appuser -d /app appuser

WORKDIR /app

# Install minimal runtime dependencies
RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y curl && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Ensure application directory is writable by appuser
RUN chown -R appuser:appuser /app

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
ENV HOME=/app

# Switch to non-root user
USER appuser

# Default command to run the bootstrap
CMD ["python", "main.py"]
