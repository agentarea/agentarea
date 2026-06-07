"""Application service for governance policy rule management."""

from uuid import UUID

from agentarea_common.audit import audited
from agentarea_common.base.repository_factory import RepositoryFactory

from ..domain.policies import EffectivePolicy
from ..domain.rules import PolicyEffect, PolicyRule, PolicySubjectType
from ..infrastructure.repository import (
    PolicyRuleRepository,
    TaskPolicySnapshotRepository,
)


class GovernancePolicyService:
    """Coordinates policy rule persistence and audit boundaries."""

    def __init__(self, repository_factory: RepositoryFactory):
        self.repository_factory = repository_factory
        self._rule_repository = repository_factory.create_repository(PolicyRuleRepository)
        self._snapshot_repository = repository_factory.create_repository(
            TaskPolicySnapshotRepository
        )

    async def list_rules(
        self,
        *,
        subject_type: PolicySubjectType | None = None,
        subject_id: str | None = None,
        effect: PolicyEffect | None = None,
        target: str | None = None,
        enabled: bool | None = None,
    ) -> list[PolicyRule]:
        """List policy rules in the current workspace."""
        return await self._rule_repository.list_rules(
            subject_type=subject_type,
            subject_id=subject_id,
            effect=effect,
            target=target,
            enabled=enabled,
        )

    async def get_rule(self, *, rule_id: UUID | str) -> PolicyRule | None:
        """Read one policy rule in the current workspace."""
        return await self._rule_repository.get(rule_id)

    @audited(
        "governance_policy.create",
        resource_type="governance_policy",
        resource_id_param="subject_id",
    )
    async def create_rule(self, *, rule: PolicyRule, subject_id: str) -> PolicyRule:
        """Create a new policy rule."""
        return await self._rule_repository.create(rule)

    @audited(
        "governance_policy.update",
        resource_type="governance_policy",
        resource_id_param="rule_id",
    )
    async def update_rule(self, *, rule_id: UUID | str, **fields) -> PolicyRule | None:
        """Partially update a policy rule."""
        return await self._rule_repository.update(rule_id, **fields)

    @audited(
        "governance_policy.set_enabled",
        resource_type="governance_policy",
        resource_id_param="rule_id",
    )
    async def set_rule_enabled(
        self, *, rule_id: UUID | str, enabled: bool
    ) -> PolicyRule | None:
        """Enable or disable a policy rule."""
        return await self._rule_repository.set_enabled(rule_id, enabled)

    @audited(
        "governance_policy.delete",
        resource_type="governance_policy",
        resource_id_param="rule_id",
    )
    async def delete_rule(self, *, rule_id: UUID | str) -> bool:
        """Delete a policy rule."""
        return await self._rule_repository.delete(rule_id)

    async def get_task_policy_snapshot(
        self,
        *,
        task_id: UUID,
    ) -> EffectivePolicy | None:
        """Read an immutable effective policy snapshot for a task."""
        return await self._snapshot_repository.get_snapshot(task_id=task_id)
