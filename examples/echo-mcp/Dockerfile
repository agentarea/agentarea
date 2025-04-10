# syntax=docker.io/docker/dockerfile:1

FROM python:3.12-slim AS base

# Build stage
FROM base AS builder
WORKDIR /app

# Install uv
RUN pip install uv

# Copy dependency files
COPY pyproject.toml uv.lock* ./

# Install dependencies with uv
RUN uv pip install --system -r pyproject.toml

# Runtime stage
FROM base AS runner
WORKDIR /app

# Copy installed dependencies from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages

# Copy application code
COPY . .

# Run the application
CMD ["python", "main.py"]
