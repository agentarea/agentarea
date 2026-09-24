"""Client (agent-proxy) repository."""

from uuid import UUID

from agentarea_agents.domain.skill_models import Skill
from agentarea_common.auth.context import UserContext
from agentarea_common.base.workspace_scoped_repository import WorkspaceScopedRepository
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from agentarea_mcp.domain.client_models import (
    Client,
    client_mcp_instances,
    client_skills,
)
from agentarea_mcp.domain.mpc_server_instance_model import MCPServerInstance


class ClientRepository(WorkspaceScopedRepository[Client]):
    """Repository for Client entities with junction table helpers."""

    def __init__(self, session: AsyncSession, user_context: UserContext):
        super().__init__(session, Client, user_context)

    @staticmethod
    def _scoped_links(workspace_id: str) -> tuple:
        """Load only the linked children that live in the client's workspace."""
        return (
            selectinload(Client.skills.and_(Skill.workspace_id == workspace_id)),
            selectinload(Client.mcp_instances.and_(MCPServerInstance.workspace_id == workspace_id)),
        )

    async def get_by_id(self, id: UUID | str, creator_scoped: bool = False) -> Client | None:  # type: ignore[override]
        query = (
            select(Client)
            .where(Client.id == id)
            .where(self._get_workspace_filter())
            .options(*self._scoped_links(self.user_context.workspace_id))
            .execution_options(populate_existing=True)
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_accessible_by_id(self, id: UUID | str) -> Client | None:
        """Resolve a client at the request boundary across authorized workspaces.

        Repository CRUD remains bound to the active workspace. This lookup is
        reserved for resource-addressed endpoints: it finds the resource only
        inside the caller's already-resolved workspace allowlist, after which
        the request binds to the resource workspace before constructing other
        workspace-scoped dependencies.
        """
        accessible = self.user_context.accessible_workspaces or [self.user_context.workspace_id]
        located = await self.session.execute(
            select(Client.workspace_id).where(Client.id == id, Client.workspace_id.in_(accessible))
        )
        workspace_id = located.scalar_one_or_none()
        if workspace_id is None:
            return None
        query = (
            select(Client)
            .where(Client.id == id)
            .options(*self._scoped_links(workspace_id))
            .execution_options(populate_existing=True)
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def list_all(
        self, limit: int | None = None, offset: int | None = None, **filters
    ) -> list[Client]:  # type: ignore[override]
        query = (
            select(Client)
            .where(self._get_workspace_filter())
            .options(*self._scoped_links(self.user_context.workspace_id))
        )
        for field, value in filters.items():
            if hasattr(Client, field):
                query = query.where(getattr(Client, field) == value)
        if offset is not None:
            query = query.offset(offset)
        if limit is not None:
            query = query.limit(limit)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    # --- Skill junction helpers ---

    async def add_skill(self, client_id: UUID | str, skill_id: UUID | str) -> None:
        stmt = (
            insert(client_skills)
            .values(client_id=client_id, skill_id=skill_id)
            .on_conflict_do_nothing()
        )
        await self.session.execute(stmt)
        await self.session.commit()

    async def remove_skill(self, client_id: UUID | str, skill_id: UUID | str) -> None:
        stmt = delete(client_skills).where(
            client_skills.c.client_id == client_id,
            client_skills.c.skill_id == skill_id,
        )
        await self.session.execute(stmt)
        await self.session.commit()

    # --- MCP instance junction helpers ---

    async def add_mcp_instance(
        self,
        client_id: UUID | str,
        mcp_instance_id: UUID | str,
        namespace_prefix: str | None = None,
    ) -> None:
        stmt = (
            insert(client_mcp_instances)
            .values(
                client_id=client_id,
                mcp_instance_id=mcp_instance_id,
                namespace_prefix=namespace_prefix,
            )
            .on_conflict_do_update(
                index_elements=["client_id", "mcp_instance_id"],
                set_={"namespace_prefix": namespace_prefix},
            )
        )
        await self.session.execute(stmt)
        await self.session.commit()

    async def remove_mcp_instance(self, client_id: UUID | str, mcp_instance_id: UUID | str) -> None:
        stmt = delete(client_mcp_instances).where(
            client_mcp_instances.c.client_id == client_id,
            client_mcp_instances.c.mcp_instance_id == mcp_instance_id,
        )
        await self.session.execute(stmt)
        await self.session.commit()

    async def get_instance_namespaces(self, client_id: UUID | str) -> dict[str, str]:
        """Return {mcp_instance_id: namespace_prefix} for the client's own instances."""
        query = select(
            client_mcp_instances.c.mcp_instance_id,
            client_mcp_instances.c.namespace_prefix,
        ).where(client_mcp_instances.c.client_id == str(client_id))
        result = await self.session.execute(query)
        return {str(row[0]): row[1] for row in result.all() if row[1]}
