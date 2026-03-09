FROM python:3.12-slim

# Install Node.js (for npx-based MCP servers)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Install uv (for uvx-based MCP servers)
RUN pip install --no-cache-dir uv

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bridge.py .

ENV PORT=8080
EXPOSE 8080

ENTRYPOINT ["python", "bridge.py"]
