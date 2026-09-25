"""Writes to a workspace's model specs, which carry the per-token prices."""

from typing import Any
from uuid import UUID

from agentarea_common.auth.authorization import assert_workspace_admin

from agentarea_llm.domain.models import ModelSpec
from agentarea_llm.infrastructure.model_spec_repository import ModelSpecRepository


class ModelSpecService:
    """Every price write is workspace-admin work.

    Spend caps are computed from price times tokens, so whoever sets a price
    decides whether a budget ever trips. A zero price is legitimate for free or
    local models; the guard is on who writes it, not on its value.
    """

    def __init__(self, repository: ModelSpecRepository) -> None:
        self.repository = repository

    async def create(self, **fields: Any) -> ModelSpec:
        await assert_workspace_admin(self.repository.user_context)
        return await self.repository.create(**fields)

    async def update(self, model_spec_id: UUID, **fields: Any) -> ModelSpec | None:
        await assert_workspace_admin(self.repository.user_context)
        return await self.repository.update(model_spec_id, **fields)

    async def delete(self, model_spec_id: UUID) -> bool:
        await assert_workspace_admin(self.repository.user_context)
        return await self.repository.delete(model_spec_id)

    async def upsert(self, **fields: Any) -> ModelSpec:
        await assert_workspace_admin(self.repository.user_context)
        return await self.repository.upsert_by_provider_and_model_kwargs(**fields)
