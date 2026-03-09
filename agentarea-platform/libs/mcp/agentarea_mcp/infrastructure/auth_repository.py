"""Repositories for MCP auth configs, OAuth links/sessions, compound MCPs and skills."""

from datetime import datetime
from uuid import UUID

from agentarea_common.auth.context import UserContext
from agentarea_common.base.workspace_scoped_repository import WorkspaceScopedRepository
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from agentarea_mcp.domain.auth_models import (
    CompoundMCP,
    CompoundMCPMember,
    MCPAccessToken,
    MCPAuthConfig,
    MCPOAuthLink,
    MCPOAuthSession,
)


class MCPAuthConfigRepository(WorkspaceScopedRepository[MCPAuthConfig]):
    def __init__(self, session: AsyncSession, user_context: UserContext) -> None:
        super().__init__(session, MCPAuthConfig, user_context)

    async def list_by_auth_type(self, auth_type: str) -> list[MCPAuthConfig]:
        """List auth configs filtered by auth type within the workspace."""
        return await self.list_all(auth_type=auth_type)

    async def get_linked_instance_ids(self, config_id: UUID) -> list[str]:
        """Return IDs of MCP server instances linked to this auth config.

        Used to prevent deletion of configs that are still in use.
        """
        from agentarea_mcp.domain.mpc_server_instance_model import MCPServerInstance

        result = await self.session.execute(
            select(MCPServerInstance.id).where(
                MCPServerInstance.auth_config_id == config_id,
                MCPServerInstance.workspace_id == self.user_context.workspace_id,
            )
        )
        return [str(row[0]) for row in result.fetchall()]


class MCPAccessTokenRepository(WorkspaceScopedRepository[MCPAccessToken]):
    def __init__(self, session: AsyncSession, user_context: UserContext) -> None:
        super().__init__(session, MCPAccessToken, user_context)

    async def get_by_hash(self, token_hash: str) -> MCPAccessToken | None:
        """Look up a token by its SHA-256 hash (no workspace filter — hash is globally unique)."""
        result = await self.session.execute(
            select(MCPAccessToken).where(MCPAccessToken.token_hash == token_hash)
        )
        return result.scalar_one_or_none()

    async def increment_access_count(self, token_id: UUID) -> None:
        """Atomically increment access_count and update last_accessed_at."""
        await self.session.execute(
            update(MCPAccessToken)
            .where(MCPAccessToken.id == token_id)
            .values(
                access_count=MCPAccessToken.access_count + 1,
                last_accessed_at=datetime.utcnow(),
            )
        )
        await self.session.commit()


class MCPOAuthLinkRepository(WorkspaceScopedRepository[MCPOAuthLink]):
    def __init__(self, session: AsyncSession, user_context: UserContext) -> None:
        super().__init__(session, MCPOAuthLink, user_context)

    async def get_by_token(self, token: str) -> MCPOAuthLink | None:
        """Look up an OAuth link by its shareable token (no workspace filter — token is unique)."""
        result = await self.session.execute(
            select(MCPOAuthLink).where(MCPOAuthLink.token == token)
        )
        return result.scalar_one_or_none()

    async def list_by_instance(self, mcp_instance_id: UUID) -> list[MCPOAuthLink]:
        """List all OAuth links for a given MCP instance within the workspace."""
        return await self.list_all(mcp_instance_id=mcp_instance_id)

    async def increment_access_count(self, link_id: UUID) -> None:
        """Atomically increment access_count and update last_accessed_at."""
        await self.session.execute(
            update(MCPOAuthLink)
            .where(MCPOAuthLink.id == link_id)
            .values(
                access_count=MCPOAuthLink.access_count + 1,
                last_accessed_at=datetime.utcnow(),
            )
        )
        await self.session.commit()


class MCPOAuthSessionRepository:
    """Repository for OAuth sessions (not workspace-scoped — sessions belong to links)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_token(self, session_token: str) -> MCPOAuthSession | None:
        result = await self.session.execute(
            select(MCPOAuthSession).where(MCPOAuthSession.session_token == session_token)
        )
        return result.scalar_one_or_none()

    async def create(self, oauth_session: MCPOAuthSession) -> MCPOAuthSession:
        self.session.add(oauth_session)
        await self.session.commit()
        await self.session.refresh(oauth_session)
        return oauth_session

    async def delete_expired(self) -> int:
        """Delete all expired sessions. Returns count removed."""
        result = await self.session.execute(
            select(MCPOAuthSession).where(MCPOAuthSession.expires_at < datetime.utcnow())
        )
        expired = result.scalars().all()
        for s in expired:
            await self.session.delete(s)
        await self.session.commit()
        return len(expired)


class CompoundMCPRepository(WorkspaceScopedRepository[CompoundMCP]):
    def __init__(self, session: AsyncSession, user_context: UserContext) -> None:
        super().__init__(session, CompoundMCP, user_context)

    async def get_members(self, compound_id: UUID) -> list[CompoundMCPMember]:
        """Return ordered member rows for a compound MCP."""
        result = await self.session.execute(
            select(CompoundMCPMember)
            .where(CompoundMCPMember.compound_id == compound_id)
            .order_by(CompoundMCPMember.order)
        )
        return list(result.scalars().all())

    async def add_member(self, member: CompoundMCPMember) -> CompoundMCPMember:
        self.session.add(member)
        await self.session.commit()
        await self.session.refresh(member)
        return member

    async def remove_member(self, compound_id: UUID, mcp_instance_id: UUID) -> bool:
        result = await self.session.execute(
            select(CompoundMCPMember).where(
                CompoundMCPMember.compound_id == compound_id,
                CompoundMCPMember.mcp_instance_id == mcp_instance_id,
            )
        )
        member = result.scalar_one_or_none()
        if member is None:
            return False
        await self.session.delete(member)
        await self.session.commit()
        return True


