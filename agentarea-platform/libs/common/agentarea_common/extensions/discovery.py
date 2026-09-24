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
        except Exception as error:
            logger.exception("Failed to load extension: %s", ep.name)
            # Only record it when nothing registered this point: a second distribution
            # advertising the same name and loading fine still wins, as it would
            # have before.
            if not ExtensionRegistry.has(ep.name):
                ExtensionRegistry.record_failure(ep.name, f"{type(error).__name__}: {error}")
