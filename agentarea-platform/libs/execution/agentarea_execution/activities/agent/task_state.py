"""Task records: status, governance snapshot, monthly spend cap and delegation tasks."""

import json
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any
from uuid import UUID

from agentarea_common.auth.context import UserContext
from agentarea_common.base.tenant_scope import bind_workspace_scope
from agentarea_common.extensions.customer_pricing import get_customer_pricing
from agentarea_common.money import to_money
from agentarea_tasks.infrastructure.task_log import ERROR_CLEARING_STATUSES, TaskOutcome
from temporalio import activity

from ...interfaces import ActivityDependencies
from ...models import (
    CreateDelegationTaskRequest,
    CreateDelegationTaskResult,
    DelegatedSpendRequest,
    DelegatedSpendResult,
    MonthlySpendCapRequest,
    MonthlySpendCapResult,
    UpdateTaskGovernanceSnapshotRequest,
    UpdateTaskGovernanceSnapshotResult,
    UpdateTaskStatusRequest,
    UpdateTaskStatusResult,
)

if TYPE_CHECKING:
    from ..dependencies import ActivityServiceContainer

logger = logging.getLogger(__name__)


def task_outcome(request: UpdateTaskStatusRequest) -> TaskOutcome:
    """What a status update sets on the task row.

    The result arrives as JSON (or plain text, kept as the response) and gets the
    run's cost and token totals; the error goes to the row's ``error``; a resume
    snapshot goes into the metadata.
    """
    result: dict[str, Any] | None = None
    if request.result:
        try:
            result = json.loads(request.result)
        except (json.JSONDecodeError, TypeError):
            result = {"response": request.result}
    elif request.total_cost is not None or request.own_cost is not None:
        result = {}
    if result is not None:
        if request.total_cost is not None:
            result["total_cost"] = str(request.total_cost)
        if request.own_cost is not None:
            result["own_cost"] = str(request.own_cost)
        if request.tokens_used is not None:
            result["tokens_used"] = request.tokens_used
    metadata_patch: dict[str, Any] = {}
    if request.conversation_resume is not None:
        metadata_patch["conversation_resume"] = request.conversation_resume.model_dump()
    if request.failure_reason:
        metadata_patch["failure_reason"] = request.failure_reason
    elif request.status in ERROR_CLEARING_STATUSES:
        metadata_patch["failure_reason"] = None
    return TaskOutcome(
        status=request.status,
        result=result,
        error=request.error_message or None,
        metadata_patch=metadata_patch or None,
    )


def make_task_state_activities(
    dependencies: ActivityDependencies, container: "ActivityServiceContainer"
) -> list[Callable[..., Any]]:
    from ..dependencies import ActivityContext, create_user_context

    @activity.defn
    async def update_task_status_activity(
        request: UpdateTaskStatusRequest,
    ) -> UpdateTaskStatusResult:
        """Update task status in the database after workflow completion."""
        from uuid import UUID as _UUID

        from agentarea_tasks.infrastructure.repository import (
            TaskConversationRepository,
            TaskRepository,
        )

        from .conversation import pending_entries

        user_context = create_user_context(request.user_context_data)
        async with ActivityContext(container, user_context) as ctx:
            session = container._database.async_session_factory()
            ctx._sessions.append(session)
            task_repo = TaskRepository(session, user_context)
            if request.conversation is not None and request.conversation_pending:
                await TaskConversationRepository(session, user_context).write(
                    _UUID(request.conversation.task_id),
                    pending_entries(request.conversation.next_seq, request.conversation_pending),
                )
            try:
                outcome = task_outcome(request)
                additional_fields: dict[str, Any] = {}
                if outcome.result is not None:
                    additional_fields["result"] = outcome.result
                additional_fields.update(outcome.error_fields())
                if outcome.metadata_patch is not None:
                    task = await task_repo.get_task(_UUID(request.task_id))
                    if task is None:
                        return UpdateTaskStatusResult(success=False, error="Task not found")
                    additional_fields["metadata"] = {
                        **(task.metadata or {}),
                        **outcome.metadata_patch,
                    }

                updated = await task_repo.update_status(
                    _UUID(request.task_id), request.status, **additional_fields
                )
                if updated:
                    return UpdateTaskStatusResult(success=True)
                return UpdateTaskStatusResult(success=False, error="Task not found")
            except Exception as e:
                # Raised, not returned: the workflow does not read the result, and
                # only a raised error gets the retries that ride out an outage.
                logger.error(f"Failed to update task status: {e}", exc_info=True)
                raise

    @activity.defn
    async def update_task_governance_snapshot_activity(
        request: UpdateTaskGovernanceSnapshotRequest,
    ) -> UpdateTaskGovernanceSnapshotResult:
        """Persist the policy revision before a waiting workflow resumes."""
        from uuid import UUID as _UUID

        from agentarea_tasks.infrastructure.repository import TaskRepository

        user_context = create_user_context(request.user_context_data)
        async with ActivityContext(container, user_context) as ctx:
            session = container._database.async_session_factory()
            ctx._sessions.append(session)
            task_repo = TaskRepository(session, user_context)
            task = await task_repo.get_task(_UUID(request.task_id))
            if task is None:
                return UpdateTaskGovernanceSnapshotResult(
                    success=False,
                    error="Task not found",
                )
            metadata = dict(task.metadata or {})
            metadata["governance_snapshot"] = request.governance_snapshot
            updated = await task_repo.update(
                _UUID(request.task_id),
                task_metadata=metadata,
            )
            if updated is None:
                return UpdateTaskGovernanceSnapshotResult(
                    success=False,
                    error="Task not found",
                )
            return UpdateTaskGovernanceSnapshotResult(success=True)

    @activity.defn
    async def check_monthly_spend_cap_activity(
        request: MonthlySpendCapRequest,
    ) -> MonthlySpendCapResult:
        """Read month-to-date spend of the workspace and of the agent against their caps."""
        from agentarea_governance.domain.policies import BudgetPolicy
        from agentarea_tasks.infrastructure.repository import TaskRepository
        from agentarea_tasks.model_spend_caps import current_budget

        user_context = create_user_context(request.user_context_data)
        agent_spent = None
        llm_cap_message = None
        cap_usd = request.cap_usd
        agent_cap_usd = request.agent_cap_usd
        llm_caps = BudgetPolicy.model_validate({"spend_caps": request.llm_caps or None})
        async with ActivityContext(container, user_context) as ctx:
            session = container._database.async_session_factory()
            ctx._sessions.append(session)
            if request.current_caps:
                budget = await current_budget(
                    session,
                    user_context,
                    UUID(request.agent_id) if request.agent_id else None,
                    None,
                )
                cap_usd = budget.monthly_spend_cap_usd if budget else None
                agent_cap_usd = budget.agent_monthly_spend_cap_usd if budget else None
                llm_caps = BudgetPolicy(
                    spend_caps=[
                        cap
                        for cap in (budget.spend_caps or [] if budget else [])
                        if cap.category == "llm" and cap.period != "run"
                    ]
                    or None
                )
            tasks = TaskRepository(session, user_context)
            spent = to_money(await tasks.sum_spend_mtd())
            if agent_cap_usd is not None:
                if not request.agent_id:
                    raise ValueError("an agent spend cap check needs the run's agent_id")
                agent_spent = to_money(await tasks.sum_spend_mtd(agent_id=UUID(request.agent_id)))
            if llm_caps.spend_caps:
                reached = await tasks.monthly_llm_cap_reached(
                    llm_caps,
                    UUID(request.agent_id) if request.agent_id else None,
                )
                if reached is not None:
                    scope = "Agent" if reached.agent_id else "Workspace"
                    llm_cap_message = (
                        f"{scope} monthly LLM spend cap reached "
                        f"({reached.spent} {reached.currency}/{reached.cap} {reached.currency})"
                    )
        return MonthlySpendCapResult(
            exceeded=cap_usd is not None and spent >= cap_usd,
            month_to_date_usd=spent,
            cap_usd=cap_usd,
            currency=get_customer_pricing().currency(),
            agent_exceeded=(
                agent_spent is not None
                and agent_cap_usd is not None
                and agent_spent >= agent_cap_usd
            ),
            agent_month_to_date_usd=agent_spent,
            agent_cap_usd=agent_cap_usd,
            llm_cap_message=llm_cap_message,
        )

    @activity.defn
    async def delegated_task_spend_activity(
        request: DelegatedSpendRequest,
    ) -> DelegatedSpendResult:
        """What a delegated agent's task has spent, every line of it."""
        from agentarea_tasks.infrastructure.repository import TaskRepository

        user_context = create_user_context(request.user_context_data)
        async with ActivityContext(container, user_context) as ctx:
            session = container._database.async_session_factory()
            ctx._sessions.append(session)
            spent = await TaskRepository(session, user_context).sum_task_spend(request.task_id)
        return DelegatedSpendResult(spent=to_money(spent))

    @activity.defn
    async def create_delegation_task_activity(
        request: CreateDelegationTaskRequest,
    ) -> CreateDelegationTaskResult:
        """Create a task record in DB for agent delegation."""
        try:
            from agentarea_common.base.repository_factory import RepositoryFactory
            from agentarea_common.config import get_database
            from agentarea_governance.domain.policies import (
                BudgetPolicy,
                PolicyDocument,
                effective_policy_from_json,
            )
            from agentarea_tasks.domain.models import TaskProvenance
            from agentarea_tasks.infrastructure.repository import TaskRepository
            from agentarea_tasks.task_service import TaskService
            from agentarea_tasks.temporal_task_manager import TemporalTaskManager

            if request.parent_effective_policy is None:
                raise ValueError(
                    "delegation request is missing the parent effective-policy snapshot"
                )
            parent_effective_policy = effective_policy_from_json(request.parent_effective_policy)
            parent_effective_policy.require_runtime_contract()
            if request.run_budget_usd is None:
                raise ValueError("delegation request is missing its allocated run budget")

            database = get_database()
            async with database.async_session_factory() as session:
                user_context = UserContext(
                    user_id=request.user_id,
                    workspace_id=request.workspace_id,
                )
                bind_workspace_scope(user_context.workspace_id)
                repository_factory = RepositoryFactory(session, user_context)
                task_repository = repository_factory.create_repository(TaskRepository)
                task_manager = TemporalTaskManager(
                    task_repository=task_repository,
                    temporal_executor=dependencies.workflow_executor,
                )

                task_service = TaskService(
                    repository_factory=repository_factory,
                    event_broker=dependencies.event_broker,
                    task_manager=task_manager,
                )

                task = await task_service.create_task_with_policy(
                    agent_id=UUID(request.target_agent_id),
                    description=f"Delegated task to {request.target_agent_name}",
                    workspace_id=request.workspace_id,
                    user_id=request.user_id,
                    title="Delegation from agent",
                    query=request.message,
                    parameters={
                        "source": "agent_delegation",
                        "parent_agent_id": request.parent_agent_id,
                        "parent_task_id": request.parent_task_id,
                    },
                    metadata_overrides={
                        "created_via": "agent_delegation",
                        "parent_agent_id": request.parent_agent_id,
                        "parent_task_id": request.parent_task_id,
                    },
                    task_policy=PolicyDocument(
                        budget=BudgetPolicy(
                            run_budget_usd=request.run_budget_usd,
                        )
                    ),
                    upper_bound_policy=parent_effective_policy,
                    require_model=True,
                    execution_id=request.execution_id,
                    provenance=TaskProvenance(
                        origin_type="agent",
                        origin_id=request.parent_task_id,
                        causation_id=request.parent_task_id,
                        parent_task_id=UUID(request.parent_task_id),
                    ),
                )

                logger.info(
                    f"Created delegation task {task.id} for agent {request.target_agent_name}"
                )

                return CreateDelegationTaskResult(
                    task_id=task.id,
                    status="created",
                    effective_policy=task.effective_policy,
                )

        except Exception as e:
            logger.error(f"Failed to create delegation task: {e}", exc_info=True)
            raise

    return [
        update_task_status_activity,
        update_task_governance_snapshot_activity,
        check_monthly_spend_cap_activity,
        create_delegation_task_activity,
        delegated_task_spend_activity,
    ]
