"""Resolve a stored icon reference into a browser-usable URL.

Registries store ``icon`` as data: either a short id naming a built-in SVG under
``/static/icons/<namespace>/`` or a full URL carried by a (possibly remote)
registry entry. The icon is the single source of truth, so this never derives
the host from the incoming request — a request that arrived via the frontend
proxy host would otherwise produce an icon URL pointing at a host that cannot
serve ``/static``. Built-in icons are pinned to the API's configured public base
instead.

Keeping the resolution here rather than in the frontend is deliberate: which
providers or channels exist is an open set that grows by configuration, and the
UI must not carry a table of them.
"""

from agentarea_common.config.app import get_app_settings

CHANNEL_ICON_NAMESPACE = "channels"


def build_icon_url(namespace: str, icon: str | None) -> str | None:
    """Map a stored ``icon`` to a public URL, or ``None`` if unset.

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
    return f"{base}/static/icons/{namespace}/{icon}.svg"
