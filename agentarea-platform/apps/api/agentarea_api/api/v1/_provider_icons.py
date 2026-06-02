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

    - A full URL (``http(s)://``) passes through unchanged — this is how a
      remote registry entry supplies its own icon.
    - Anything else is treated as a built-in id and resolved against
      ``API_BASE_URL``. Note we deliberately do NOT pass through root-relative
      paths (``/...``): the icon renders in the browser on the *frontend*
      origin, so ``/static/...`` would resolve against a host that cannot serve
      it — the exact 404/500 this function exists to avoid.
    """
    if not icon:
        return None
    if icon.startswith(("http://", "https://")):
        return icon
    base = get_app_settings().API_BASE_URL.rstrip("/")
    return f"{base}/static/icons/providers/{icon}.svg"
