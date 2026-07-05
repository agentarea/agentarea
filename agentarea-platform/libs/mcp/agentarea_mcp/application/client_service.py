"""Client (agent-proxy) application service."""

import logging
from uuid import UUID

from agentarea_mcp.domain.client_models import Client
from agentarea_mcp.infrastructure.client_repository import ClientRepository
from agentarea_mcp.schemas.client_dto import ClientCreate, ClientUpdate

logger = logging.getLogger(__name__)


class ClientService:
    """Service for managing clients (agent-proxies) and their associations."""

    def __init__(self, repository: ClientRepository):
        self.repository = repository

    async def create_client(self, payload: ClientCreate) -> Client:
        return await self.repository.create(
            name=payload.name,
            description=payload.description,
            kind=payload.kind,
            source_project_id=payload.source_project_id,
        )

    async def update_client(
        self, client_id: UUID | str, payload: ClientUpdate
    ) -> Client | None:
        patch = payload.model_dump(exclude_unset=True)
        return await self.repository.update(client_id, **patch)

    async def get(self, client_id: UUID | str) -> Client | None:
        return await self.repository.get_by_id(client_id)

    async def list(
        self, limit: int | None = None, offset: int | None = None
    ) -> list[Client]:
        return await self.repository.list_all(limit=limit, offset=offset)

    async def delete(self, client_id: UUID | str) -> bool:
        return await self.repository.delete(client_id)

    async def set_source_project(
        self, client_id: UUID | str, project_id: UUID | str | None
    ) -> Client | None:
        return await self.repository.update(
            client_id, source_project_id=str(project_id) if project_id else None
        )

    # --- Skill associations ---

    async def add_skill(self, client_id: UUID | str, skill_id: UUID | str) -> None:
        await self.repository.add_skill(client_id, skill_id)

    async def remove_skill(self, client_id: UUID | str, skill_id: UUID | str) -> None:
        await self.repository.remove_skill(client_id, skill_id)

    # --- MCP instance associations ---

    async def add_mcp_instance(
        self,
        client_id: UUID | str,
        mcp_instance_id: UUID | str,
        namespace_prefix: str | None = None,
    ) -> None:
        await self.repository.add_mcp_instance(client_id, mcp_instance_id, namespace_prefix)

    async def remove_mcp_instance(
        self, client_id: UUID | str, mcp_instance_id: UUID | str
    ) -> None:
        await self.repository.remove_mcp_instance(client_id, mcp_instance_id)
