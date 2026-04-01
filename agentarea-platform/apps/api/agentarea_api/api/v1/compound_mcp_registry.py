"""Global registry of running compound MCP proxy ASGI apps.

Keys are slugs (e.g. "compound-my-tools"), values are Starlette ASGI apps
produced by FastMCP.streamable_http_app().

The CompoundMCPMiddleware in main.py checks incoming requests against this
registry and delegates matching paths to the compound proxy app.
"""

from starlette.types import ASGIApp

# slug -> ASGI app
registry: dict[str, ASGIApp] = {}
