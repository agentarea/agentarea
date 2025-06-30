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

# Use uv to install dependencies and project packages
RUN uv sync --frozen

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
COPY --from=builder /app/.venv /app/.venv

# Copy project files
COPY libs ./libs
COPY apps/worker ./apps/worker
COPY pyproject.toml ./

# Set proper permissions
RUN chown -R appuser:appuser /app

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PATH="/app/.venv/bin:$PATH"

# Switch to non-root user
USER appuser

# Stay in root directory
WORKDIR /app

CMD ["python", "-m", "agentarea_worker.cli", "start"] 