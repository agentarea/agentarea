"""Client (agent-proxy) application service."""

import logging
from collections.abc import Callable
from typing import Any
from uuid import UUID

from agentarea_agents.infrastructure.skill_repository import SkillRepository
from agentarea_common.auth.context import UserContext
from agentarea_common.base.workspace_scoped_repository import WorkspaceScopedRepository
from agentarea_common.exceptions.errors import NotFoundError
from sqlalchemy.ext.asyncio import AsyncSession

from agentarea_mcp.domain.client_models import (
    Client,
    ClientMcpInstanceLink,
    ClientPlatformToolset,
)
from agentarea_mcp.infrastructure.client_repository import ClientRepository
from agentarea_mcp.infrastructure.repository import MCPServerInstanceRepository
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
        )

    async def update_client(self, client_id: UUID | str, payload: ClientUpdate) -> Client | None:
        patch = payload.model_dump(exclude_unset=True)
        if await self.repository.update(client_id, **patch) is None:
            return None
        return await self.repository.get_by_id(client_id)

    async def get(self, client_id: UUID | str) -> Client | None:
        return await self.repository.get_by_id(client_id)

    async def list(
        self,
        limit: int | None = None,
        offset: int | None = None,
        ids: set[str] | None = None,
    ) -> list[Client]:
        """List clients, narrowed to ``ids`` when the caller has a readable set."""
        return await self.repository.list_all(limit=limit, offset=offset, ids=ids)

    async def delete(self, client_id: UUID | str) -> bool:
        return await self.repository.delete(client_id)

    # --- Associations ---
    # Link rows carry no workspace of their own: both ends are resolved in the
    # caller's workspace first, and a miss is a 404 whether the id is foreign
    # or unknown.

    async def _in_workspace(
        self,
        repository_class: Callable[[AsyncSession, UserContext], WorkspaceScopedRepository[Any]],
        record_id: UUID | str,
        label: str,
    ) -> UUID:
        try:
            record_uuid = UUID(str(record_id))
        except ValueError:
            raise NotFoundError(f"{label} not found") from None
        repository = repository_class(self.repository.session, self.repository.user_context)
        if await repository.get_by_id(record_uuid) is None:
            raise NotFoundError(f"{label} not found")
        return record_uuid

    async def _client_id(self, client_id: UUID | str) -> UUID:
        return await self._in_workspace(ClientRepository, client_id, "Client")

    async def add_skill(self, client_id: UUID | str, skill_id: UUID | str) -> None:
        await self.repository.add_skill(
            await self._client_id(client_id),
            await self._in_workspace(SkillRepository, skill_id, "Skill"),
        )

    async def remove_skill(self, client_id: UUID | str, skill_id: UUID | str) -> None:
        await self.repository.remove_skill(await self._client_id(client_id), skill_id)

    async def add_mcp_instance(
        self,
        client_id: UUID | str,
        mcp_instance_id: UUID | str,
        namespace_prefix: str | None = None,
        allowed_tools: list[str] | None = None,
    ) -> None:
        await self.repository.add_mcp_instance(
            await self._client_id(client_id),
            await self._in_workspace(MCPServerInstanceRepository, mcp_instance_id, "MCP instance"),
            namespace_prefix,
            allowed_tools,
        )

    async def remove_mcp_instance(self, client_id: UUID | str, mcp_instance_id: UUID | str) -> None:
        await self.repository.remove_mcp_instance(await self._client_id(client_id), mcp_instance_id)

    async def instance_links(
        self, client_ids: list[UUID]
    ) -> dict[str, dict[str, ClientMcpInstanceLink]]:
        return await self.repository.get_instance_links(client_ids)

    # The caller resolves ``toolset`` to a platform toolset's namespace: which
    # toolsets exist is known to the API that serves them, not to this library.

    async def set_platform_toolset(
        self, client_id: UUID | str, toolset: str, disabled_methods: list[str] | None
    ) -> None:
        await self.repository.set_platform_toolset(
            await self._client_id(client_id), toolset, disabled_methods
        )

    async def remove_platform_toolset(self, client_id: UUID | str, toolset: str) -> None:
        await self.repository.remove_platform_toolset(await self._client_id(client_id), toolset)

    async def platform_toolsets(self, client_ids: list[UUID]) -> dict[str, list[ClientPlatformToolset]]:
        return await self.repository.get_platform_toolsets(client_ids)
