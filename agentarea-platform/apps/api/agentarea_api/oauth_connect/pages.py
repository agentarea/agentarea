"""Frontend pages an OAuth flow starts from and returns to."""

import logging
import urllib.parse

from agentarea_common.config import get_settings

logger = logging.getLogger(__name__)

CALLBACK_PATH = "/v1/oauth/callback"


def callback_uri() -> str:
    """The one redirect URI every provider sends the browser back to."""
    return f"{get_settings().app.API_URL.rstrip('/')}{CALLBACK_PATH}"


def frontend_base(return_to: str = "") -> str:
    """The frontend origin to return to: ``return_to``'s when it is AGENTAREA_APP_URL's own."""
    default_base = get_settings().app.APP_URL.rstrip("/")
    if not return_to:
        return default_base
    parsed = urllib.parse.urlparse(return_to)
    expected = urllib.parse.urlparse(default_base)
    if (
        parsed.scheme in {"http", "https"}
        and parsed.netloc
        and (parsed.scheme, parsed.netloc) == (expected.scheme, expected.netloc)
    ):
        return f"{parsed.scheme}://{parsed.netloc}"
    logger.warning("Rejected non-matching return_to origin: %s", return_to)
    return default_base


def connect_page_url(workspace_slug: str, instance_id: str) -> str:
    """The page a person opens to connect one instance: an agent's connect link.

    It carries no secret and authenticates nothing; the page needs the
    person's own session before it starts any authorization.
    """
    base = get_settings().app.APP_URL.rstrip("/")
    if not base:
        raise RuntimeError("AGENTAREA_APP_URL is not set: a connect link has no page to point at")
    return f"{base}/w/{workspace_slug}/connect/{instance_id}"


def catalog_connect_page_url(workspace_slug: str, registry_item_id: str) -> str:
    """The page a person opens to sign in to a catalog API connection."""
    return connect_page_url(workspace_slug, f"catalog/{registry_item_id}")


def mcp_instance_landing_url(return_to: str, workspace_slug: str, instance_id: str) -> str:
    """The connect page when ``return_to`` is exactly the one for this workspace
    and instance, else the connection's detail page.

    Its query and fragment are dropped, never carried back.
    """
    if return_to:
        parsed = urllib.parse.urlsplit(return_to)
        page = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
        connect_page = connect_page_url(workspace_slug, instance_id)
        if page == connect_page:
            return connect_page
    return f"{frontend_base(return_to)}/w/{workspace_slug}/connections/{instance_id}"


def openapi_connection_landing_url(return_to: str, workspace_slug: str, connection_id: str) -> str:
    """An API connection's detail page."""
    return f"{frontend_base(return_to)}/w/{workspace_slug}/connections/openapi/{connection_id}"
