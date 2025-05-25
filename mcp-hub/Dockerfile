FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

# Install Node.js and npm to get npx alongwith uvx for MCP running
RUN apt-get update && \
    apt-get install -y --no-install-recommends nodejs npm && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Create working directory
WORKDIR /app

# Enable bytecode compilation
ENV UV_COMPILE_BYTECODE=1

# Copy from the cache instead of linking since it's a mounted volume
ENV UV_LINK_MODE=copy

# Install the project's dependencies using the lockfile and settings
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-dev

# Then, add the rest of the project source code and install it
# Installing separately from its dependencies allows optimal layer caching
ADD . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# Place executables in the environment at the front of the path
# ENV PATH="/app/.venv/bin:$PATH"

# Reset the entrypoint, don't invoke `uv`
ENTRYPOINT []

# Expose the port your app runs on
EXPOSE 8000
EXPOSE 3000
EXPOSE 5000
EXPOSE 8888

# Run the FastAPI application by default
# Uses `fastapi dev` to enable hot-reloading when the `watch` sync occurs
# Uses `--host 0.0.0.0` to allow access from outside the container
#CMD ["fastapi", "dev", "--host", "0.0.0.0", "src/uv_docker_example"]

# With local package in editable mode
# CMD ["fastmcp", "dev", "main.py", "--ui-port", "3000", "--server-port", "5000", "--with-editable", "."]
CMD ["uv", "run", "main.py"]
