"""A catalog item a person connects an HTTP API from.

Only an active ``mcp_servers`` registry's item whose spec is an OpenAPI
connection qualifies; how it authenticates — OAuth or keys — is the caller's
business. Shared by the OAuth flow and the key form so both refuse the same items.
"""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from agentarea_common.auth.context import UserContext
from agentarea_registry.domain.models import RegistryItem
from agentarea_registry.infrastructure.repository import RegistryItemRepository, RegistryRepository
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class CatalogApiItem:
    id: UUID
    name: str
    description: str | None
    spec: dict[str, Any]
    item: RegistryItem


async def load_catalog_api_item(
    item_id: UUID, user_context: UserContext, session: AsyncSession
) -> CatalogApiItem:
    item = await RegistryItemRepository(session, user_context).get_by_id(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Catalog connection not found")
    registry = await RegistryRepository(session, user_context).get_by_id(item.registry_id)
    spec = item.spec or {}
    if (
        registry is None
        or not registry.is_active
        or registry.registry_type != "mcp_servers"
        or spec.get("connection_type") != "openapi"
    ):
        raise HTTPException(
            status_code=400, detail="Catalog item is not a one-click API connection"
        )
    return CatalogApiItem(
        id=item_id, name=item.name, description=item.description, spec=spec, item=item
    )
