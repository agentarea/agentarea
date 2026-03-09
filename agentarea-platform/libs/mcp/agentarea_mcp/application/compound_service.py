"""Service for Compound MCPs."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from agentarea_mcp.domain.auth_models import (
    ROUTING_MODE_PARALLEL,
    CompoundMCP,
    CompoundMCPMember,
)
from agentarea_mcp.infrastructure.auth_repository import (
    CompoundMCPRepository,
)

logger = logging.getLogger(__name__)

# Maximum nesting depth for compound MCPs and skills
MAX_NESTING_DEPTH = 3


class CompoundMCPService:
    """Business logic for compound MCP creation and management."""

    def __init__(self, repository: CompoundMCPRepository) -> None:
        self._repo = repository

    async def create(
        self,
        name: str,
        routing_mode: str = ROUTING_MODE_PARALLEL,
        description: str | None = None,
    ) -> CompoundMCP:
        compound = await self._repo.create(
            name=name,
            routing_mode=routing_mode,
            description=description,
        )
        logger.info("Created CompoundMCP %s (mode=%s)", compound.id, routing_mode)
        return compound

    async def get(self, compound_id: UUID) -> CompoundMCP | None:
        return await self._repo.get(compound_id)

    async def list(self) -> list[CompoundMCP]:
        return await self._repo.list_all()

    async def update(
        self,
        compound_id: UUID,
        name: str | None = None,
        routing_mode: str | None = None,
        description: str | None = None,
    ) -> CompoundMCP | None:
        updates: dict[str, Any] = {}
        if name is not None:
            updates["name"] = name
        if routing_mode is not None:
            updates["routing_mode"] = routing_mode
        if description is not None:
            updates["description"] = description
        if updates:
            return await self._repo.update(compound_id, **updates)
        return await self._repo.get(compound_id)

    async def delete(self, compound_id: UUID) -> bool:
        return await self._repo.delete(compound_id)

    # ------------------------------------------------------------------
    # Member management
    # ------------------------------------------------------------------

    async def add_member(
        self,
        compound_id: UUID,
        mcp_instance_id: UUID,
        order: int = 0,
        config: dict[str, Any] | None = None,
    ) -> CompoundMCPMember:
        """Add a member MCP instance to the compound."""
        member = CompoundMCPMember(
            compound_id=compound_id,
            mcp_instance_id=mcp_instance_id,
            order=order,
            config=config or {},
        )
        return await self._repo.add_member(member)

    async def remove_member(self, compound_id: UUID, mcp_instance_id: UUID) -> bool:
        return await self._repo.remove_member(compound_id, mcp_instance_id)

    async def get_members(self, compound_id: UUID) -> list[CompoundMCPMember]:
        return await self._repo.get_members(compound_id)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    async def check_circular_reference(
        self, compound_id: UUID, candidate_instance_id: UUID
    ) -> bool:
        """Return True if adding candidate_instance_id would create a cycle.

        For now, this is a simple check — compound MCPs reference instances,
        not other compounds, so direct circular refs are not possible.
        This method exists for future nested-compound support.
        """
        return False

    def get_tool_namespace(self, member: CompoundMCPMember) -> str:
        """Return the namespace prefix for tools from this member.

        If the member config has ``namespace_prefix`` use that, otherwise
        use the first 8 chars of the instance ID as a stable prefix.
        """
        return member.config.get(
            "namespace_prefix", str(member.mcp_instance_id)[:8]
        )

    def get_tool_aliases(self, member: CompoundMCPMember) -> dict[str, str]:
        """Return tool name alias mapping for this member: {original: alias}."""
        return member.config.get("aliases", {})

    def get_status_summary(
        self, member_statuses: dict[str, str]
    ) -> str:
        """Aggregate individual member statuses into a compound status.

        Args:
            member_statuses: mapping of mcp_instance_id -> status string

        Returns:
            "running" if all members running, "degraded" if some, "stopped" otherwise.
        """
        if not member_statuses:
            return "unknown"
        statuses = set(member_statuses.values())
        if statuses == {"running"}:
            return "running"
        if "running" in statuses:
            return "degraded"
        return "stopped"


