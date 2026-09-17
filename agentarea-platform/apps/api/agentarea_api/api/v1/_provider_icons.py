"""Resolve a provider's stored icon reference into a browser-usable URL.

Thin wrapper over the shared resolver in ``_icons`` — see it for why the host is
taken from ``API_BASE_URL`` rather than the incoming request.
"""

from agentarea_api.api.v1._icons import build_icon_url

PROVIDER_ICON_NAMESPACE = "providers"


def build_provider_icon_url(icon: str | None) -> str | None:
    """Map a stored provider ``icon`` to a public URL, or ``None`` if unset."""
    return build_icon_url(PROVIDER_ICON_NAMESPACE, icon)
