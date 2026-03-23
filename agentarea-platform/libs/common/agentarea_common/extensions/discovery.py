"""Entrypoint-based plugin discovery."""

import logging
from importlib.metadata import entry_points

from .registry import ExtensionRegistry

logger = logging.getLogger(__name__)

ENTRYPOINT_GROUP = "agentarea.extensions"


def discover_extensions() -> None:
    """Scan installed packages for agentarea extensions.

    Each entrypoint must point to a factory callable that returns
    an instance of the corresponding interface.
    """
    discovered = entry_points(group=ENTRYPOINT_GROUP)
    for ep in discovered:
        try:
            factory = ep.load()
            ExtensionRegistry.register(ep.name, factory)
            logger.info("Discovered extension: %s from %s", ep.name, ep.value)
        except Exception:
            logger.exception("Failed to load extension: %s", ep.name)
