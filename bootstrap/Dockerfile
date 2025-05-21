# Build stage
FROM python:3.12-slim as builder

WORKDIR /app

# Install uv
RUN pip install uv

COPY pyproject.toml uv.lock ./

# Use uv to install dependencies
# Fix process substitution syntax error by using a temporary file instead
RUN uv pip compile pyproject.toml --resolution=highest > requirements.txt && \
    uv pip install --system -r requirements.txt

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

# Copy installed dependencies from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy project files
COPY . .

# Set proper permissions
RUN chown -R appuser:appuser /app

# Set environment variables
ENV PYTHONPATH=/app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Switch to non-root user
USER appuser

# Define healthcheck
# HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
#     CMD curl -f http://localhost:8000/health || exit 1

EXPOSE 8000

# Drop capabilities and set security options
USER root
RUN apt-get update && apt-get install -y --no-install-recommends libcap2-bin && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* && \
    setcap 'cap_net_bind_service=+ep' /usr/local/bin/python3.12

USER appuser

# ENTRYPOINT ["python", "-m", "cli"]

CMD [ "python", "-m", "cli", "serve" ]