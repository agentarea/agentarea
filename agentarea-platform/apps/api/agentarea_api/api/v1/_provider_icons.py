"""Resolve a provider's stored icon reference into a browser-usable URL.

The provider registry stores ``icon`` as data: either a short id that maps to a
built-in SVG shipped under ``/static/icons/providers/`` or a full URL carried by
a (possibly remote) registry entry. The icon is the single source of truth, so
this never derives the host from the incoming request — a request that arrived
via the frontend proxy host would otherwise produce an icon URL pointing at a
host that cannot serve ``/static`` (the 404/500 we used to see). Built-in icons
are pinned to the API's configured public base instead.
"""

from agentarea_common.config.app import get_app_settings


def build_provider_icon_url(icon: str | None) -> str | None:
    """Map a stored provider ``icon`` to a public URL, or ``None`` if unset.

    - Full URLs (``http(s)://``) and absolute paths (``/...``) pass through
      unchanged — this is how remote registry entries supply their own icons.
    - A bare id resolves against ``API_BASE_URL`` to the built-in static asset.
    """
    if not icon:
        return None
    if icon.startswith(("http://", "https://", "/")):
        return icon
    base = get_app_settings().API_BASE_URL.rstrip("/")
    return f"{base}/static/icons/providers/{icon}.svg"
