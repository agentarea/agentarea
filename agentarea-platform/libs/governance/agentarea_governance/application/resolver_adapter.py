"""Concrete PolicyResolverPort implementation backed by governance infra."""

from __future__ import annotations

from uuid import UUID

from agentarea_common.base.repository_factory import RepositoryFactory

from ..domain.policies import (
    EffectivePolicy,
    PolicyDocument,
    PolicyResolver,
)
from ..infrastructure.repository import (
    GovernancePolicyRepository,
    TaskPolicySnapshotRepository,
)


class GovernancePolicyResolver:
    """Resolve and persist governance policy through governance repositories.

    Satisfies ``agentarea_common.ports.policy_resolver.PolicyResolverPort``.
    """

    def __init__(self, repository_factory: RepositoryFactory):
        self._policy_repository = repository_factory.create_repository(GovernancePolicyRepository)
        self._snapshot_repository = repository_factory.create_repository(
            TaskPolicySnapshotRepository
        )

    async def resolve(
        self,
        *,
        workspace_id: str,
        agent_id: UUID | None = None,
        task_id: UUID | None = None,
        task_policy: PolicyDocument | None = None,
    ) -> EffectivePolicy:
        if not workspace_id:
            return EffectivePolicy()

        source_ids, policies = await self._policy_repository.get_chain(
            workspace_id=workspace_id,
            agent_id=agent_id,
            task_id=task_id,
        )

        if task_policy is not None:
            policies.append(task_policy)

        return PolicyResolver().resolve(policies, source_policy_ids=source_ids)

    async def snapshot(
        self,
        *,
        task_id: UUID,
        effective_policy: EffectivePolicy,
    ) -> None:
        await self._snapshot_repository.create_snapshot(
            task_id=task_id, effective_policy=effective_policy
        )
