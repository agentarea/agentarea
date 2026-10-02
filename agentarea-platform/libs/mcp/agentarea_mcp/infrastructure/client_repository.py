"""Client (agent-proxy) repository."""

from collections.abc import Collection
from typing import Any
from uuid import UUID

from agentarea_agents.domain.skill_models import Skill
from agentarea_common.auth.context import UserContext
from agentarea_common.base.tenant_scope import unscoped
from agentarea_common.base.workspace_scoped_repository import (
    WorkspaceScopedRepository,
    as_record_ids,
)
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from agentarea_mcp.domain.client_models import (
    Client,
    ClientMcpInstanceLink,
    ClientPlatformToolset,
    client_mcp_instances,
    client_platform_toolsets,
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

    async def get_by_id(self, id: UUID | str, creator_scoped: bool = False) -> Client | None:
        query = (
            select(Client)
            .where(Client.id == id)
            .where(
                self._get_creator_workspace_filter()
                if creator_scoped
                else self._get_workspace_filter()
            )
            .options(*self._scoped_links(self.user_context.workspace_id))
            .execution_options(populate_existing=True)
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    @staticmethod
    async def locate_workspace(
        session: AsyncSession, id: UUID | str, accessible_workspaces: list[str]
    ) -> str | None:
        """The workspace a client lives in, if it is one of ``accessible_workspaces``.

        Repository CRUD stays bound to one workspace. This lookup is reserved for
        resource-addressed endpoints (``/mcp/clients/{id}``): it finds the client
        only inside the caller's already-resolved workspace allowlist, after
        which the request enters that workspace before constructing any other
        workspace-scoped dependency.
        """
        with unscoped("a client endpoint names a client; its workspace is the one to enter"):
            located = await session.execute(
                select(Client.workspace_id).where(
                    Client.id == id, Client.workspace_id.in_(accessible_workspaces)
                )
            )
        workspace_id = located.scalar_one_or_none()
        return str(workspace_id) if workspace_id is not None else None

    async def list_all(
        self,
        limit: int | None = None,
        offset: int | None = None,
        ids: set[str] | None = None,
        **filters: Any,
    ) -> list[Client]:
        query = (
            select(Client)
            .where(self._get_workspace_filter())
            .options(*self._scoped_links(self.user_context.workspace_id))
        )
        if ids is not None:
            query = query.where(Client.id.in_(as_record_ids(ids)))
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
        allowed_tools: list[str] | None = None,
    ) -> None:
        """Attach an instance, or replace how an attached one is served."""
        settings = {"namespace_prefix": namespace_prefix, "allowed_tools": allowed_tools}
        stmt = (
            insert(client_mcp_instances)
            .values(client_id=client_id, mcp_instance_id=mcp_instance_id, **settings)
            .on_conflict_do_update(index_elements=["client_id", "mcp_instance_id"], set_=settings)
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

    async def get_instance_links(
        self, client_ids: Collection[UUID | str]
    ) -> dict[str, dict[str, ClientMcpInstanceLink]]:
        """``{client_id: {mcp_instance_id: link}}`` for this workspace's clients."""
        query = (
            select(
                client_mcp_instances.c.client_id,
                client_mcp_instances.c.mcp_instance_id,
                client_mcp_instances.c.namespace_prefix,
                client_mcp_instances.c.allowed_tools,
            )
            .join(Client, Client.id == client_mcp_instances.c.client_id)
            .where(self._get_workspace_filter())
            .where(client_mcp_instances.c.client_id.in_([UUID(str(i)) for i in client_ids]))
        )
        links: dict[str, dict[str, ClientMcpInstanceLink]] = {}
        for client_id, instance_id, prefix, allowed in (await self.session.execute(query)).all():
            links.setdefault(str(client_id), {})[str(instance_id)] = ClientMcpInstanceLink(
                namespace_prefix=prefix, allowed_tools=allowed
            )
        return links

    # --- Platform toolset links ---

    async def set_platform_toolset(
        self, client_id: UUID | str, toolset: str, disabled_methods: list[str] | None
    ) -> None:
        """Attach a toolset, or replace the methods an attached one leaves out."""
        stmt = (
            insert(client_platform_toolsets)
            .values(client_id=client_id, toolset=toolset, disabled_methods=disabled_methods)
            .on_conflict_do_update(
                index_elements=["client_id", "toolset"],
                set_={"disabled_methods": disabled_methods},
            )
        )
        await self.session.execute(stmt)
        await self.session.commit()

    async def remove_platform_toolset(self, client_id: UUID | str, toolset: str) -> None:
        stmt = delete(client_platform_toolsets).where(
            client_platform_toolsets.c.client_id == client_id,
            client_platform_toolsets.c.toolset == toolset,
        )
        await self.session.execute(stmt)
        await self.session.commit()

    async def get_platform_toolsets(
        self, client_ids: Collection[UUID | str]
    ) -> dict[str, list[ClientPlatformToolset]]:
        """``{client_id: [toolset, ...]}`` for this workspace's clients."""
        query = (
            select(
                client_platform_toolsets.c.client_id,
                client_platform_toolsets.c.toolset,
                client_platform_toolsets.c.disabled_methods,
            )
            .join(Client, Client.id == client_platform_toolsets.c.client_id)
            .where(self._get_workspace_filter())
            .where(client_platform_toolsets.c.client_id.in_([UUID(str(i)) for i in client_ids]))
            .order_by(client_platform_toolsets.c.toolset)
        )
        toolsets: dict[str, list[ClientPlatformToolset]] = {}
        for client_id, toolset, disabled in (await self.session.execute(query)).all():
            toolsets.setdefault(str(client_id), []).append(
                ClientPlatformToolset(toolset=toolset, disabled_methods=disabled)
            )
        return toolsets
