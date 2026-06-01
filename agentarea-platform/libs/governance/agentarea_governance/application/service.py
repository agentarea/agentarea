"""Application service for governance policy management."""

from uuid import UUID

from agentarea_common.audit import audited
from agentarea_common.base.repository_factory import RepositoryFactory

from ..domain.policies import (
    EffectivePolicy,
    PolicyDocument,
    PolicyResolver,
    PolicyScopeType,
    PolicyValidationError,
    PolicyValidator,
)
from ..infrastructure.repository import (
    GovernancePolicyRecord,
    GovernancePolicyRepository,
    TaskPolicySnapshotRepository,
)


class GovernancePolicyService:
    """Coordinates policy persistence, validation, and audit boundaries."""

    def __init__(self, repository_factory: RepositoryFactory):
        self.repository_factory = repository_factory
        self._policy_repository = repository_factory.create_repository(GovernancePolicyRepository)
        self._snapshot_repository = repository_factory.create_repository(
            TaskPolicySnapshotRepository
        )

    async def list_policies(
        self,
        *,
        scope_type: PolicyScopeType | None = None,
        scope_id: str | None = None,
        enabled: bool | None = True,
    ) -> list[GovernancePolicyRecord]:
        """List source policies in the current workspace."""
        return await self._policy_repository.list_policies(
            scope_type=scope_type,
            scope_id=scope_id,
            enabled=enabled,
        )

    async def get_policy(
        self,
        *,
        scope_type: PolicyScopeType,
        scope_id: str,
    ) -> GovernancePolicyRecord | None:
        """Read one enabled source policy in the current workspace."""
        records = await self._policy_repository.list_policies(
            scope_type=scope_type,
            scope_id=scope_id,
            enabled=True,
        )
        return records[0] if records else None

    @audited(
        "governance_policy.upsert",
        resource_type="governance_policy",
        resource_id_param="scope_id",
    )
    async def upsert_policy(
        self,
        *,
        scope_type: PolicyScopeType,
        scope_id: str,
        document: PolicyDocument,
        enabled: bool = True,
        parent_agent_id: UUID | None = None,
    ) -> GovernancePolicyRecord:
        """Create or update a source policy after monotonic validation."""
        source_ids, policies = await self._policy_chain_for_update(
            scope_type=scope_type,
            scope_id=scope_id,
            parent_agent_id=parent_agent_id,
            document=document,
        )
        PolicyValidator(PolicyResolver()).validate_chain(list(policies), source_policy_ids=source_ids)

        policy_id, saved_document = await self._policy_repository.upsert_scope_policy(
            scope_type=scope_type,
            scope_id=scope_id,
            document=document,
            enabled=enabled,
        )
        return GovernancePolicyRecord(
            id=policy_id,
            scope_type=str(scope_type),
            scope_id=scope_id,
            document=saved_document,
            enabled=enabled,
        )

    async def get_task_policy_snapshot(
        self,
        *,
        task_id: UUID,
    ) -> EffectivePolicy | None:
        """Read an immutable effective policy snapshot for a task."""
        return await self._snapshot_repository.get_snapshot(task_id=task_id)

    async def _policy_chain_for_update(
        self,
        *,
        scope_type: PolicyScopeType,
        scope_id: str,
        parent_agent_id: UUID | None,
        document: PolicyDocument,
    ) -> tuple[list[str], list[PolicyDocument]]:
        """Build the higher-scope chain used to reject persisted loosening."""
        if scope_type == PolicyScopeType.WORKSPACE:
            return [], [document]

        workspace_id = self.repository_factory.user_context.workspace_id
        source_ids: list[str] = []
        policies: list[PolicyDocument] = []

        workspace_policy = await self._policy_repository.get_scope_policy(
            scope_type=PolicyScopeType.WORKSPACE,
            scope_id=workspace_id,
        )
        if workspace_policy:
            source_id, policy = workspace_policy
            source_ids.append(source_id)
            policies.append(policy)

        if scope_type == PolicyScopeType.TASK:
            if parent_agent_id is None:
                raise PolicyValidationError(
                    "parent_agent_id is required for task-scoped persisted policies"
                )
            agent_policy = await self._policy_repository.get_scope_policy(
                scope_type=PolicyScopeType.AGENT,
                scope_id=str(parent_agent_id),
            )
            if agent_policy:
                source_id, policy = agent_policy
                source_ids.append(source_id)
                policies.append(policy)

        policies.append(document)
        return source_ids, policies
