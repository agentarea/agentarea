"""OAuth apps the platform operator registered with providers that have no DCR.

GitHub's authorization server cannot register AgentArea dynamically, so the
operator registers one app and configures it in AGENTAREA_MCP_OAUTH_APPS; every
workspace then connects through it. A workspace's auth config names the app by
issuer and never holds its client credentials. Which app serves a connection is
decided in ``oauth_profile.platform_app_for``.
"""

from urllib.parse import urlparse

from agentarea_common.config import MCPOAuthApp, get_settings


def url_origin(url: str) -> str:
    """``scheme://host[:port]`` of any URL, or "" when it has none."""
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


def platform_oauth_apps() -> tuple[MCPOAuthApp, ...]:
    """Every app the operator configured."""
    return get_settings().mcp.OAUTH_APPS


def platform_oauth_app(issuer: str) -> MCPOAuthApp | None:
    """The operator's app for ``issuer``, if one is configured."""
    return get_settings().mcp.oauth_app_for(issuer)
