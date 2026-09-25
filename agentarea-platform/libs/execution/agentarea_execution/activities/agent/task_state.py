"""Task records: status, governance snapshot, monthly spend cap and delegation tasks."""

import json
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any
from uuid import UUID

from agentarea_common.auth.context import UserContext
from agentarea_common.money import to_money
from temporalio import activity

from ...interfaces import ActivityDependencies
from ...models import (
    CreateDelegationTaskRequest,
    CreateDelegationTaskResult,
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

        from agentarea_tasks.infrastructure.repository import TaskRepository

        user_context = create_user_context(request.user_context_data)
        async with ActivityContext(container, user_context) as ctx:
            session = container._database.async_session_factory()
            ctx._sessions.append(session)
            task_repo = TaskRepository(session, user_context)
            try:
                additional_fields = {}
                if (
                    request.result
                ):  # Task model expects result as dict, but request carries it as JSON string
                    try:
                        result_dict = json.loads(request.result)
                    except (json.JSONDecodeError, TypeError):
                        result_dict = {"response": request.result}
                    if request.total_cost is not None:
                        # Serialize Money (Decimal) to string for JSON compatibility
                        result_dict["total_cost"] = str(request.total_cost)
                    if request.own_cost is not None:
                        result_dict["own_cost"] = str(request.own_cost)
                    additional_fields["result"] = result_dict
                elif request.total_cost is not None or request.own_cost is not None:
                    # Serialize Money (Decimal) to string for JSON compatibility
                    additional_fields["result"] = {}
                    if request.total_cost is not None:
                        additional_fields["result"]["total_cost"] = str(request.total_cost)
                    if request.own_cost is not None:
                        additional_fields["result"]["own_cost"] = str(request.own_cost)
                if request.error_message:
                    # Tasks table stores this as `error`, not `error_message`.
                    additional_fields["error"] = request.error_message

                updated = await task_repo.update_status(
                    _UUID(request.task_id), request.status, **additional_fields
                )
                if updated:
                    return UpdateTaskStatusResult(success=True)
                return UpdateTaskStatusResult(success=False, error="Task not found")
            except Exception as e:
                logger.error(f"Failed to update task status: {e}")
                return UpdateTaskStatusResult(success=False, error=str(e))

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
        """Read the workspace's month-to-date spend against the run's monthly cap."""
        from agentarea_tasks.infrastructure.repository import TaskRepository

        user_context = create_user_context(request.user_context_data)
        async with ActivityContext(container, user_context) as ctx:
            session = container._database.async_session_factory()
            ctx._sessions.append(session)
            spent = to_money(await TaskRepository(session, user_context).sum_spend_mtd())
        return MonthlySpendCapResult(
            exceeded=spent >= request.cap_usd,
            month_to_date_usd=spent,
            cap_usd=request.cap_usd,
        )

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
    ]
