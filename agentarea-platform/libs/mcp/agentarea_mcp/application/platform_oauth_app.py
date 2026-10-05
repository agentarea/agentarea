"""OAuth apps the platform operator registered with providers that have no DCR.

GitHub's authorization server cannot register AgentArea dynamically, so the
operator registers one app and configures it in AGENTAREA_MCP_OAUTH_APPS; every
workspace then connects through it. A workspace's auth config names the app by
issuer and never holds its client credentials.
"""

import logging
from urllib.parse import urlparse

from agentarea_common.config import MCPOAuthApp, get_settings

logger = logging.getLogger(__name__)


def url_origin(url: str) -> str:
    """``scheme://host[:port]`` of any URL, or "" when it has none."""
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


def platform_oauth_app(issuer: str) -> MCPOAuthApp | None:
    """The operator's app for ``issuer``, if one is configured."""
    return get_settings().mcp.oauth_app_for(issuer)


def find_platform_oauth_app(issuer: str, mcp_url: str) -> MCPOAuthApp | None:
    """The platform app that may authorize ``mcp_url`` through ``issuer``, if any."""
    app = platform_oauth_app(issuer)
    if app is None:
        return None
    if url_origin(mcp_url) not in app.resource_origins:
        logger.info("Platform OAuth app for %s does not serve %s", app.issuer, url_origin(mcp_url))
        return None
    return app
