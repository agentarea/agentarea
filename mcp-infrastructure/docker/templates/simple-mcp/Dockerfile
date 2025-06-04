FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Set up working directory
WORKDIR /app

# Copy Python project files
COPY pyproject.toml .

# Install dependencies with uv (no lock file for simplicity)
RUN uv sync --no-dev

# Copy application code
COPY mcp_server.py .

# Create non-root user
RUN useradd --create-home --shell /bin/bash mcpuser && \
    chown -R mcpuser:mcpuser /app
USER mcpuser

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Expose port
EXPOSE 8000

# Start the application using uv
CMD ["uv", "run", "python", "mcp_server.py"] 