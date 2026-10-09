"""The workspace's connections that were made from a catalog item.

An MCP instance records its catalog item through its spec (a workspace copy of
a catalog spec keeps ``registry_item_id``); an OpenAPI connection records it on
its own row, and a manual one has none.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal
from uuid import UUID

from agentarea_common.auth.context import UserContext
from agentarea_mcp.domain.models import MCPServer
from agentarea_mcp.domain.mpc_server_instance_model import MCPServerInstance
from agentarea_openapi.domain.models import OpenAPIConnection
from pydantic import BaseModel
from sqlalchemy import String, cast, literal, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession


class CatalogConnection(BaseModel):
    """One existing connection made from a catalog item."""

    id: UUID
    kind: Literal["mcp", "openapi"]
    name: str


def _uuids(values: Iterable[UUID | str]) -> list[UUID]:
    coerced: list[UUID] = []
    for value in values:
        try:
            coerced.append(value if isinstance(value, UUID) else UUID(str(value)))
        except ValueError:
            continue
    return coerced


class CatalogConnectionRepository:
    """MCP instances and OpenAPI connections of the workspace, by catalog item."""

    def __init__(self, session: AsyncSession, user_context: UserContext):
        self.session = session
        self.user_context = user_context

    async def by_catalog_item(
        self, item_ids: Iterable[UUID | str], readable: set[str]
    ) -> dict[str, list[CatalogConnection]]:
        """Connections among ``readable`` per catalog item id, oldest first.

        Items without any are absent. One query for every item.
        """
        items = _uuids(item_ids)
        allowed = _uuids(readable)
        if not items or not allowed:
            return {}
        workspace_id = self.user_context.workspace_id

        mcp = (
            select(
                MCPServerInstance.id.label("id"),
                MCPServerInstance.name.label("name"),
                literal("mcp").label("kind"),
                MCPServer.registry_item_id.label("item_id"),
                MCPServerInstance.created_at.label("created_at"),
            )
            .join(MCPServer, cast(MCPServer.id, String) == MCPServerInstance.server_spec_id)
            .where(
                MCPServerInstance.workspace_id == workspace_id,
                MCPServer.registry_item_id.in_(items),
                MCPServerInstance.id.in_(allowed),
            )
        )
        openapi = select(
            OpenAPIConnection.id.label("id"),
            OpenAPIConnection.name.label("name"),
            literal("openapi").label("kind"),
            OpenAPIConnection.registry_item_id.label("item_id"),
            OpenAPIConnection.created_at.label("created_at"),
        ).where(
            OpenAPIConnection.workspace_id == workspace_id,
            OpenAPIConnection.registry_item_id.in_(items),
            OpenAPIConnection.id.in_(allowed),
        )
        combined = union_all(mcp, openapi).subquery()
        rows = await self.session.execute(
            select(combined).order_by(combined.c.created_at, combined.c.name)
        )

        found: dict[str, list[CatalogConnection]] = {}
        for row in rows:
            found.setdefault(str(row.item_id), []).append(
                CatalogConnection(id=row.id, kind=row.kind, name=row.name)
            )
        return found
