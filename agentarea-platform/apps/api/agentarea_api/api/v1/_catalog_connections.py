"""The caller's connections that were made from a catalog item.

MCP instances and OpenAPI connections are graph-governed, so a caller sees only
the ones the graph lets them read.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from typing import Any
from uuid import UUID

from agentarea_api.api.deps.services import DatabaseSessionDep
from agentarea_api.repositories.catalog_connection_repository import (
    CatalogConnection,
    CatalogConnectionRepository,
)
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.dependencies import UserContextDep
from agentarea_common.auth.resource_visibility import readable_resource_ids
from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "CatalogConnection",
    "CatalogConnectionsLookup",
    "get_catalog_connections_lookup",
    "other_catalog_connections",
    "readable_catalog_connections",
    "with_existing_connections",
]


async def readable_catalog_connections(
    session: AsyncSession,
    user_context: UserContext,
    item_ids: Iterable[UUID | str],
) -> dict[str, list[CatalogConnection]]:
    """The caller's connections per catalog item, filtered by what the graph lets them read."""
    items = list(item_ids)
    if not items:
        return {}
    readable = await readable_resource_ids(user_context.user_id)
    return await CatalogConnectionRepository(session, user_context).by_catalog_item(items, readable)


async def other_catalog_connections(
    session: AsyncSession,
    user_context: UserContext,
    registry_item_id: UUID | str,
    exclude: UUID,
) -> list[CatalogConnection]:
    """The caller's other connections made from the same catalog item as ``exclude``."""
    found = await readable_catalog_connections(session, user_context, [registry_item_id])
    return [c for c in found.get(str(registry_item_id), []) if c.id != exclude]


def with_existing_connections(
    action: dict[str, Any], existing: list[CatalogConnection]
) -> dict[str, Any]:
    """A connect action that tells the agent the workspace already holds a connection."""
    if not existing:
        return action
    names = ", ".join(c.name for c in existing)
    return {
        **action,
        "existing_connections": [c.model_dump(mode="json") for c in existing],
        "message": (
            f"{action['message']} This workspace already has a connection from the same "
            f"catalog item: {names}."
        ),
    }


CatalogConnectionsLookup = Callable[
    [Iterable[UUID | str]], Awaitable[dict[str, list[CatalogConnection]]]
]


def get_catalog_connections_lookup(
    session: DatabaseSessionDep, user_context: UserContextDep
) -> CatalogConnectionsLookup:
    """The request's ``readable_catalog_connections``, for routes that list catalog items."""

    async def lookup(item_ids: Iterable[UUID | str]) -> dict[str, list[CatalogConnection]]:
        return await readable_catalog_connections(session, user_context, item_ids)

    return lookup
