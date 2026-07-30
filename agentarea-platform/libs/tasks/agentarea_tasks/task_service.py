"""Task service for AgentArea platform.

High-level service that orchestrates task management by:
1. Handling task persistence through TaskRepository
2. Delegating task execution to injected TaskManager
3. Managing task lifecycle and events
4. Validating agent existence before task submission
"""

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from agentarea_common.audit import audited
from agentarea_common.events.broker import EventBroker
from agentarea_common.money import Money, serialize_money, to_money
from agentarea_common.ports.policy_resolver import PolicyResolverPort
from agentarea_governance.domain.policies import (
    EffectivePolicy,
    ExecutionLimitsPolicy,
    PolicyDocument,
    PolicyResolver,
    PolicyValidationError,
    effective_policy_from_json,
)

from .domain.base_service import BaseTaskService
from .domain.exceptions import AgentModelNotConfiguredError, BudgetCapExceededError
from .domain.interfaces import BaseTaskManager
from .domain.models import AgentTask
from .infrastructure.repository import TaskRepository
from .schemas.dto import RunCreate

if TYPE_CHECKING:
    from agentarea_common.base import RepositoryFactory

logger = logging.getLogger(__name__)

# Terminal Temporal statuses that may upgrade a stale DB status.
# In-flight Temporal statuses ("running", "unknown") never overwrite the DB
# because the workflow may legitimately stay alive in await_follow_up
# after the activity has already persisted "completed" to the DB.
_TERMINAL_WORKFLOW_STATUSES = frozenset({"completed", "failed", "cancelled", "canceled"})
_PACKAGE_INSTALL_PROFILES = frozenset({"allowed", "locked"})
_GOVERNANCE_SNAPSHOT_METADATA_KEY = "governance_snapshot"


def _agent_package_install_profile(agent: Any) -> str:
    """Resolve the agent's sandbox profile from its shell-tool configuration."""
    tools = getattr(agent, "tools", None)
    if not isinstance(tools, list):
        return "allowed"
    for tool in tools:
        if not isinstance(tool, dict) or tool.get("name") != "agentarea/shell":
            continue
        settings = tool.get("settings")
        if not isinstance(settings, dict):
            return "allowed"
        profile = settings.get("package_install")
        if profile is None:
            return "allowed"
        if profile not in _PACKAGE_INSTALL_PROFILES:
            raise ValueError(f"invalid agent package_install profile: {profile}")
        return str(profile)
    return "allowed"


class TaskService(BaseTaskService):
    """High-level service for task management that orchestrates persistence and execution."""

    def __init__(
        self,
        repository_factory: "RepositoryFactory",
        event_broker: EventBroker,
        task_manager: BaseTaskManager,
        policy_resolver: PolicyResolverPort | None = None,
        workflow_service: Any | None = None,
    ):
        """Initialize with repository factory, event broker, task manager, an
        optional policy resolver port, and optional workflow service.

        When ``policy_resolver`` is omitted, the governance-backed implementation
        is constructed lazily from ``repository_factory`` — DI consumers (tests,
        alternative governance backends) can inject a different port without
        forcing every call site to wire one up.
        """
        # Create repositories using factory
        task_repository = repository_factory.create_repository(TaskRepository)
        # Route domain events through the transactional outbox on this service's
        # session so they commit atomically with the task change (the worker
        # relay publishes them to the broker later). event_broker is kept as the
        # fallback for the base class when no outbox is available.
        from agentarea_common.events.outbox_publisher import OutboxPublisher

        outbox_publisher = OutboxPublisher(
            repository_factory.session, repository_factory.user_context
        )
        super().__init__(task_repository, event_broker, outbox_publisher=outbox_publisher)

        self.repository_factory = repository_factory
        self.task_manager = task_manager
        if policy_resolver is None:
            from agentarea_governance.application import GovernancePolicyResolver

            policy_resolver = GovernancePolicyResolver(repository_factory)
        self.policy_resolver = policy_resolver
        self.workflow_service = workflow_service

        # Create agent repository using factory for validation
        try:
            from agentarea_agents.infrastructure.repository import AgentRepository

            self.agent_repository = repository_factory.create_repository(AgentRepository)
        except ImportError:
            self.agent_repository = None

    async def _resolve_effective_policy(
        self,
        *,
        workspace_id: str | None,
        agent_id: UUID | None = None,
        task_id: UUID | None = None,
        task_policy: PolicyDocument | None = None,
    ) -> EffectivePolicy:
        """Resolve workspace/agent/user/task policy via the injected port.

        The per-user layer is resolved from the task creator (this service's
        UserContext), so the snapshot a task carries reflects that specific
        caller's permissions — the same agent can resolve differently per user.
        """
        if not workspace_id:
            raise ValueError("workspace_id is required to resolve runtime policy")

        return await self.policy_resolver.resolve(
            workspace_id=workspace_id,
            agent_id=agent_id,
            task_id=task_id,
            task_policy=task_policy,
            user_id=self.repository_factory.user_context.user_id,
        )

    @staticmethod
    def _with_requested_execution_limits(
        task_policy: PolicyDocument | None,
        parameters: dict[str, Any] | None,
    ) -> PolicyDocument | None:
        """Translate legacy task parameters into the typed task policy layer.

        ``max_iterations`` remains accepted at the API edge for compatibility,
        but it can only tighten the persisted workspace/agent ceiling. The
        workflow never reads the free-form parameter directly.
        """
        requested = (parameters or {}).get("max_iterations")
        if requested is None:
            return task_policy
        if isinstance(requested, bool) or not isinstance(requested, int) or requested <= 0:
            raise PolicyValidationError("parameters.max_iterations must be a positive integer")

        requested_policy = PolicyDocument(
            execution=ExecutionLimitsPolicy(max_model_turns=requested)
        )
        if task_policy is None:
            return requested_policy
        existing = (
            task_policy.execution.max_model_turns if task_policy.execution is not None else None
        )
        if existing is not None and existing != requested:
            raise PolicyValidationError(
                "execution.max_model_turns conflicts with task_policy.execution.max_model_turns"
            )
        merged = PolicyResolver().resolve([task_policy, requested_policy])
        return PolicyDocument.model_validate(
            merged.model_dump(exclude={"source_policy_ids", "resolver_version"})
        )

    async def _enforce_budget_cap(
        self,
        workspace_id: str | None,
        effective_policy: EffectivePolicy | None = None,
    ) -> None:
        """Reject task creation if the workspace has hit its policy monthly cap.

        No-op when:
        - workspace_id is missing
        - no policy monthly cap is configured
        """
        if not workspace_id:
            return

        policy = effective_policy or await self._resolve_effective_policy(workspace_id=workspace_id)
        cap_value = policy.budget.monthly_spend_cap_usd if policy.budget else None
        if cap_value is None:
            return

        cap = to_money(cap_value)
        mtd = to_money(await self.task_repository.sum_spend_mtd())
        if mtd >= cap:
            raise BudgetCapExceededError(
                workspace_id=workspace_id,
                current_mtd_usd=float(mtd),
                cap_usd=float(cap),
            )

    async def _validate_agent_exists(self, agent_id: UUID):
        """Validate that the agent exists and return the loaded entity for reuse.

        Returns the agent so callers can reuse it (e.g. for ``metadata.agent_name``)
        without a second repository round-trip. Returns ``None`` only when no
        agent_repository is wired up (test/standalone mode).

        Raises:
            ValueError: If the agent does not exist.
        """
        if not self.agent_repository:
            logger.warning("Agent repository not available - skipping agent validation")
            return None

        agent = await self.agent_repository.get(agent_id)
        if not agent:
            raise ValueError(f"Agent with ID {agent_id} does not exist")
        return agent

    @staticmethod
    def _require_agent_model(agent, agent_id: UUID, parameters: dict[str, Any] | None) -> None:
        """Fail fast when an agent has no model to run with.

        Catalog agents can be installed without a model when the workspace has
        no matching instance (``model_id`` is left unset rather than pointing at
        a non-existent model). Starting a run then fails deep inside the workflow
        with an empty model name; raise a clear, client-mappable error instead.
        A per-run ``model_override`` satisfies the requirement. ``agent`` is
        ``None`` only in test/standalone mode (no repository wired), where the
        check is skipped — mirroring ``_validate_agent_exists``.
        """
        if agent is None:
            return
        if (parameters or {}).get("model_override"):
            return
        if not getattr(agent, "model_id", None):
            raise AgentModelNotConfiguredError(agent_id)

    @audited("task.create", resource_type="task")
    async def create_task_with_policy(
        self,
        *,
        agent_id: UUID,
        description: str,
        workspace_id: str,
        parameters: dict[str, Any] | None = None,
        user_id: str | None = None,
        requires_human_approval: bool = False,
        task_id: UUID | None = None,
        title: str | None = None,
        query: str | None = None,
        metadata_overrides: dict[str, Any] | None = None,
        status: str = "submitted",
        task_policy: PolicyDocument | None = None,
        upper_bound_policy: EffectivePolicy | None = None,
        require_model: bool = False,
    ) -> AgentTask:
        """Persist a task with resolved governance policy. Does not dispatch to Temporal.

        Canonical persist-only entrypoint used by delegation activities, trigger
        prepare-only activities, and as the internal building block for
        ``create_and_execute_task_with_workflow``.

        ``require_model`` is set by the execution path so a run is rejected up
        front when the agent has no model configured; persist-only callers leave
        it ``False``.
        """
        new_task_id = task_id or uuid4()
        parameters = dict(parameters or {})
        task_policy = self._with_requested_execution_limits(task_policy, parameters)
        # Compatibility input only: once translated into the typed policy it
        # must not survive as a second runtime source of truth.
        parameters.pop("max_iterations", None)
        effective_policy = await self._resolve_effective_policy(
            workspace_id=workspace_id,
            agent_id=agent_id,
            task_id=new_task_id,
            task_policy=task_policy,
        )
        effective_policy.require_runtime_contract()
        if upper_bound_policy is not None:
            upper_bound_policy.require_runtime_contract()
            upper_bound_document = PolicyDocument.model_validate(
                upper_bound_policy.model_dump(exclude={"source_policy_ids", "resolver_version"})
            )
            effective_document = PolicyDocument.model_validate(
                effective_policy.model_dump(exclude={"source_policy_ids", "resolver_version"})
            )
            # A delegated task may be stricter than its parent, but never
            # acquire limits or capabilities the parent execution did not have.
            PolicyResolver().resolve([upper_bound_document, effective_document])
        await self._enforce_budget_cap(workspace_id, effective_policy)

        agent = await self._validate_agent_exists(agent_id)
        if require_model:
            self._require_agent_model(agent, agent_id, parameters)
        agent_name = getattr(agent, "name", "unknown") if agent else "unknown"

        metadata: dict[str, Any] = {}
        if metadata_overrides:
            metadata.update(metadata_overrides)
        metadata.setdefault("created_via", "api")
        metadata["agent_name"] = agent_name
        metadata["requires_human_approval"] = requires_human_approval
        package_install = metadata.get("package_install")
        if package_install is None:
            package_install = _agent_package_install_profile(agent)
        if package_install not in _PACKAGE_INSTALL_PROFILES:
            raise ValueError(f"invalid task package_install profile: {package_install}")
        metadata["package_install"] = package_install
        requested_execution = (
            task_policy.execution.model_dump(exclude_none=True)
            if task_policy is not None and task_policy.execution is not None
            else {}
        )
        metadata[_GOVERNANCE_SNAPSHOT_METADATA_KEY] = {
            "requested_policy": task_policy.to_json_dict() if task_policy is not None else {},
            "requested_execution": requested_execution,
            "resolved_execution": effective_policy.execution.model_dump(exclude_none=True)
            if effective_policy.execution is not None
            else {},
            "effective_policy": effective_policy.to_json_dict(),
            "resolved_at": datetime.now(UTC).isoformat(),
            "revision": 1,
        }

        task = AgentTask(
            id=new_task_id,
            title=title or description,
            description=description,
            query=query or description,
            user_id=user_id or "",
            workspace_id=workspace_id or "",
            agent_id=agent_id,
            status=status,
            task_parameters=parameters,
            metadata=metadata,
        )
        stored_task = await self.create_task(task)
        # Hand the exact DB-persisted snapshot to Temporal. Policy changes after
        # this point must not affect the run.
        stored_task.effective_policy = effective_policy.to_json_dict()
        return stored_task

    async def submit_task(self, task: AgentTask) -> AgentTask:
        """Submit a pre-built AgentTask. Thin alias delegating to the canonical
        ``create_and_execute_task_with_workflow`` so A2A and MCP callers get the
        same metadata enrichment, channel routing, and defaults as REST.

        The caller's id, title, query, task_parameters, and metadata are
        preserved (passed through as overrides). Defaults still applied:
        - ``metadata.created_via="api"`` if not set
        - ``requires_human_approval=False``
        """
        meta = task.metadata or {}
        return await self.create_and_execute_task_with_workflow(
            agent_id=task.agent_id,
            description=task.description or task.query,
            workspace_id=task.workspace_id,
            parameters=task.task_parameters or {},
            user_id=task.user_id,
            requires_human_approval=meta.get("requires_human_approval", False),
            task_id=task.id,
            title=task.title,
            query=task.query,
            metadata_overrides=meta or None,
        )

    async def start_run(
        self,
        payload: RunCreate,
        *,
        workspace_id: str,
        user_id: str | None = None,
        created_via: str = "api",
        task_id: UUID | None = None,
        trusted_metadata: dict[str, Any] | None = None,
    ) -> AgentTask:
        """Start a new agent run from a validated DTO.

        This is the payload-style public entry shared by REST, MCP toolset,
        and any other surface that wants the Pydantic-validated contract
        instead of building a ``AgentTask`` by hand. Internally it delegates
        to ``create_and_execute_task_with_workflow`` so all lifecycle, channel
        routing, and metadata defaults stay in a single place.

        Args:
            payload: Validated run parameters (agent_id, description, etc.).
            workspace_id: Owning workspace (multi-tenancy isolation; required).
            user_id: User initiating the run, when authenticated.
            created_via: Source tag stored on ``metadata.created_via``
                (defaults to ``"api"``; toolset overrides to ``"mcp"``).
            task_id: Server-reserved task identity, when the caller must commit
                task-scoped inputs before workflow dispatch.
            trusted_metadata: Trusted server-side metadata merged into the
                workflow request. REST request bodies do not populate it.

        Returns:
            The created (or routed-into) ``AgentTask`` with execution info.
        """
        metadata_overrides: dict[str, Any] = {"created_via": created_via}
        if trusted_metadata:
            metadata_overrides.update(trusted_metadata)
        if payload.project_id is not None:
            metadata_overrides["project_id"] = payload.project_id
        if payload.package_install is not None:
            metadata_overrides["package_install"] = payload.package_install

        parameters = dict(payload.parameters)
        task_policy = payload.task_policy
        if payload.execution is not None:
            legacy_value = parameters.get("max_iterations")
            requested_value = payload.execution.max_model_turns
            if legacy_value is not None and legacy_value != requested_value:
                raise PolicyValidationError(
                    "execution.max_model_turns conflicts with parameters.max_iterations"
                )
            task_policy = self._with_requested_execution_limits(
                task_policy,
                {"max_iterations": requested_value},
            )

        return await self.create_and_execute_task_with_workflow(
            agent_id=payload.agent_id,
            description=payload.description,
            workspace_id=workspace_id,
            parameters=parameters,
            user_id=user_id,
            requires_human_approval=payload.requires_human_approval,
            task_policy=task_policy,
            metadata_overrides=metadata_overrides,
            task_id=task_id,
        )

    async def reserve_run(
        self,
        payload: RunCreate,
        *,
        workspace_id: str,
        user_id: str | None = None,
        created_via: str = "api",
        task_id: UUID,
        trusted_metadata: dict[str, Any] | None = None,
    ) -> AgentTask:
        """Persist a validated task before committing task-scoped inputs.

        Multipart uploads need an authoritative owner before object storage is
        mutated. The returned task is intentionally not dispatched; callers
        commit inputs and then pass it to :meth:`dispatch_reserved_run`.
        """
        metadata_overrides: dict[str, Any] = {"created_via": created_via}
        if trusted_metadata:
            metadata_overrides.update(trusted_metadata)
        if payload.project_id is not None:
            metadata_overrides["project_id"] = payload.project_id
        if payload.package_install is not None:
            metadata_overrides["package_install"] = payload.package_install
        parameters = dict(payload.parameters)
        task_policy = payload.task_policy
        if payload.execution is not None:
            legacy_value = parameters.get("max_iterations")
            requested_value = payload.execution.max_model_turns
            if legacy_value is not None and legacy_value != requested_value:
                raise PolicyValidationError(
                    "execution.max_model_turns conflicts with parameters.max_iterations"
                )
            task_policy = self._with_requested_execution_limits(
                task_policy,
                {"max_iterations": requested_value},
            )

        return await self.create_task_with_policy(
            agent_id=payload.agent_id,
            description=payload.description,
            workspace_id=workspace_id,
            parameters=parameters,
            user_id=user_id,
            requires_human_approval=payload.requires_human_approval,
            task_id=task_id,
            metadata_overrides=metadata_overrides,
            status="preparing",
            task_policy=task_policy,
            require_model=True,
        )

    async def dispatch_reserved_run(self, task: AgentTask) -> AgentTask:
        """Dispatch a previously persisted task without creating it twice."""
        task.status = "pending"
        return await self.task_manager.submit_task(task)

    async def route_or_submit_task(self, task: AgentTask) -> AgentTask:
        """Submit a channel-originated task, routing follow-ups to an active workflow.

        Named entry point for trigger/channel callers. The routing itself — if a
        running workflow already exists for the same agent + chat_id, deliver the
        message to it as a follow-up signal instead of creating a new task — lives
        canonically in ``create_and_execute_task_with_workflow`` (reached via
        ``submit_task``). This delegates straight there so routing happens exactly
        once; doing its own routing pass here as well would query and signal the
        workflow twice on the no-match path.
        """
        return await self.submit_task(task)

    async def _try_route_to_active_workflow(
        self, task: AgentTask, chat_id: str
    ) -> AgentTask | None:
        """Try to route a message to an existing active workflow for this channel.

        Returns the existing task (with status="routed") if successful, None otherwise.
        """
        executor = getattr(self.task_manager, "temporal_executor", None)
        if not executor:
            return None

        task_repository = self.repository_factory.create_repository(TaskRepository)
        candidates = await task_repository.find_active_by_agent_and_chat(task.agent_id, chat_id)

        message_text = task.query or task.description

        for candidate in candidates:
            try:
                ok = await executor.send_workflow_command(
                    candidate.execution_id,
                    "queue_message",
                    {"message": message_text},
                )
                if not ok:
                    continue
                logger.info(
                    "Routed follow-up to workflow %s (agent=%s, chat_id=%s)",
                    candidate.execution_id,
                    task.agent_id,
                    chat_id,
                )
                # Return existing task marked as routed
                candidate_as_simple = AgentTask(
                    id=candidate.id,
                    title=task.title,
                    description=candidate.description,
                    query=task.query,
                    user_id=candidate.user_id or "",
                    workspace_id=candidate.workspace_id or "",
                    agent_id=candidate.agent_id,
                    status="routed",
                    execution_id=candidate.execution_id,
                    task_parameters=candidate.parameters,
                )
                return candidate_as_simple
            except Exception:
                logger.warning(
                    "Failed to signal workflow %s, trying next candidate",
                    candidate.execution_id,
                    exc_info=True,
                )
                continue

        return None

    async def cancel_task(self, task_id: UUID) -> bool:
        """Cancel a task."""
        return await self.task_manager.cancel_task(task_id)

    async def get_user_tasks(
        self, user_id: str, limit: int = 100, offset: int = 0
    ) -> list[AgentTask]:
        """Get tasks for a specific user."""
        return await self.list_tasks(user_id=user_id, limit=limit, offset=offset)

    async def get_agent_tasks(
        self, agent_id: UUID, limit: int = 100, offset: int = 0, creator_scoped: bool = False
    ) -> list[AgentTask]:
        """Get tasks for a specific agent."""
        # Get Task domain models from repository and convert to AgentTask
        if hasattr(self.task_repository, "list_all"):
            # Get raw TaskORM objects from workspace repository
            task_orms = await self.task_repository.list_all(
                creator_scoped=creator_scoped, limit=limit, offset=offset, agent_id=agent_id
            )
            # Convert TaskORM -> Task -> AgentTask
            tasks = [self.task_repository._orm_to_domain(task_orm) for task_orm in task_orms]
            return [self._task_to_agent_task(task) for task in tasks]
        else:
            # Fallback for repositories that don't support workspace scoping
            return await self.list_tasks(agent_id=agent_id, limit=limit, offset=offset)

    async def get_task_status(self, task_id: UUID) -> str | None:
        """Get task status."""
        task = await self.get_task(task_id)
        return task.status if task else None

    async def get_task_result(self, task_id: UUID) -> Any | None:
        """Get task result."""
        task = await self.get_task(task_id)
        return task.result if task else None

    async def get_recent_tasks(
        self,
        limit: int = 100,
        workspace_id: str | None = None,
        hours: int = 168,  # Default to 7 days
    ) -> list[AgentTask]:
        """Get recent tasks within a time period for monitoring and analytics.

        Args:
            limit: Maximum number of tasks to return
            workspace_id: Workspace ID to filter by (optional)
            hours: Number of hours back to look (default 7 days)

        Returns:
            List of recent tasks ordered by creation time (newest first)
        """
        from datetime import timedelta

        # Calculate cutoff time
        cutoff_time = datetime.now(UTC) - timedelta(hours=hours)

        try:
            if hasattr(self.task_repository, "list_all"):
                # Use workspace-aware repository method
                # Note: The base repository doesn't support created_after filtering yet,
                # so we'll get all recent tasks and filter in memory for now
                task_orms = await self.task_repository.list_all(
                    limit=limit * 2,  # Get more to account for time filtering
                    offset=0,
                )
                # Convert TaskORM -> Task -> AgentTask and filter by time
                tasks = []
                for task_orm in task_orms:
                    task = self.task_repository._orm_to_domain(task_orm)
                    agent_task = self._task_to_agent_task(task)

                    # Filter by time and workspace
                    if agent_task.created_at and agent_task.created_at >= cutoff_time:
                        if workspace_id is None or agent_task.workspace_id == workspace_id:
                            tasks.append(agent_task)

                    if len(tasks) >= limit:
                        break

                # Sort by creation time (newest first)
                tasks.sort(
                    key=lambda t: t.created_at or datetime.min.replace(tzinfo=UTC), reverse=True
                )
                return tasks[:limit]
            else:
                # Fallback for repositories without workspace scoping
                # Get all tasks and filter in memory (not ideal for production)
                all_tasks = await self.list_tasks(
                    limit=limit * 2
                )  # Get more to account for filtering

                # Filter by time and workspace
                filtered_tasks = []
                for task in all_tasks:
                    if task.created_at and task.created_at >= cutoff_time:
                        if workspace_id is None or task.workspace_id == workspace_id:
                            filtered_tasks.append(task)

                    if len(filtered_tasks) >= limit:
                        break

                # Sort by creation time (newest first)
                filtered_tasks.sort(
                    key=lambda t: t.created_at or datetime.min.replace(tzinfo=UTC), reverse=True
                )
                return filtered_tasks[:limit]

        except Exception as e:
            logger.error(f"Failed to get recent tasks: {e}")
            # Return empty list on error to not break monitoring
            return []

    async def update_task_status(
        self,
        task_id: UUID,
        status: str,
        execution_id: str | None = None,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> AgentTask | None:
        """Update task status and related fields.

        Args:
            task_id: The task ID to update
            status: The new status
            execution_id: Optional execution ID
            result: Optional task result
            error: Optional error message

        Returns:
            The updated task if found, None otherwise
        """
        task = await self.get_task(task_id)
        if not task:
            return None

        # Update the task using the AgentTask's update_status method
        task.update_status(status, execution_id=execution_id, result=result, error_message=error)

        # Persist the update
        return await self.update_task(task)

    async def list_agent_tasks(
        self, agent_id: UUID, limit: int = 100, creator_scoped: bool = False
    ) -> list[AgentTask]:
        """List tasks for an agent.

        Args:
            agent_id: The agent ID to get tasks for
            limit: Maximum number of tasks to return
            creator_scoped: If True, only return tasks created by current user

        Returns:
            List of tasks for the agent
        """
        return await self.get_agent_tasks(agent_id, limit=limit, creator_scoped=creator_scoped)

    async def list_agent_tasks_with_workflow_status(
        self, agent_id: UUID, limit: int = 100, creator_scoped: bool = False
    ) -> list[AgentTask]:
        """List tasks for an agent enriched with workflow status.

        Args:
            agent_id: The agent ID to get tasks for
            limit: Maximum number of tasks to return
            creator_scoped: If True, only return tasks created by current user

        Returns:
            List of tasks for the agent with current workflow status
        """
        tasks = await self.list_agent_tasks(agent_id, limit, creator_scoped=creator_scoped)

        if not self.workflow_service:
            logger.warning(
                "Workflow service not available - returning tasks without workflow enrichment"
            )
            return tasks

        # Enrich each task with workflow status
        enriched_tasks = []
        for task in tasks:
            enriched_task = await self._enrich_task_with_workflow_status(task)
            enriched_tasks.append(enriched_task)

        return enriched_tasks

    async def get_task_with_workflow_status(self, task_id: UUID) -> AgentTask | None:
        """Get a task enriched with workflow status.

        Args:
            task_id: The task ID to get

        Returns:
            Task with current workflow status if found, None otherwise
        """
        task = await self.get_task(task_id)
        if not task:
            return None

        if not self.workflow_service:
            logger.warning(
                "Workflow service not available - returning task without workflow enrichment"
            )
            return task

        return await self._enrich_task_with_workflow_status(task)

    async def continue_execution(
        self,
        task_id: UUID,
        *,
        additional_iterations: int = 0,
        additional_budget_usd: Money | None = None,
    ) -> dict[str, Any]:
        """Atomically grant resources to a task waiting for continuation."""
        task = await self.get_task(task_id)
        if task is None:
            return {"accepted": False, "reason": "task_not_found"}
        if task.status != "waiting_for_continuation":
            return {"accepted": False, "reason": "not_waiting_for_continuation"}
        if not task.execution_id or self.workflow_service is None:
            return {"accepted": False, "reason": "workflow_unavailable"}

        metadata = dict(task.metadata or {})
        current_snapshot = metadata.get(_GOVERNANCE_SNAPSHOT_METADATA_KEY)
        if not isinstance(current_snapshot, dict):
            return {"accepted": False, "reason": "governance_snapshot_missing"}
        current_policy_data = current_snapshot.get("effective_policy")
        if not isinstance(current_policy_data, dict):
            return {"accepted": False, "reason": "governance_snapshot_missing"}
        current_policy = effective_policy_from_json(current_policy_data)
        current_runtime = current_policy.runtime_contract()

        requested_policy = PolicyDocument.model_validate(
            current_snapshot.get("requested_policy") or {}
        )
        requested_data = requested_policy.to_json_dict()
        if additional_iterations:
            execution = dict(requested_data.get("execution") or {})
            execution["max_model_turns"] = current_runtime.max_model_turns + additional_iterations
            requested_data["execution"] = execution
        if additional_budget_usd is not None:
            budget = dict(requested_data.get("budget") or {})
            budget["run_budget_usd"] = serialize_money(
                current_runtime.run_budget_usd + additional_budget_usd
            )
            requested_data["budget"] = budget
        requested_policy = PolicyDocument.model_validate(requested_data)

        try:
            next_policy = await self._resolve_effective_policy(
                workspace_id=task.workspace_id,
                agent_id=task.agent_id,
                task_id=task.id,
                task_policy=requested_policy,
            )
            next_policy.runtime_contract()
        except PolicyValidationError:
            return {"accepted": False, "reason": "policy_ceiling"}

        resolved_execution = next_policy.execution
        if resolved_execution is None:
            return {"accepted": False, "reason": "governance_snapshot_missing"}
        next_snapshot = {
            "requested_policy": requested_policy.to_json_dict(),
            "requested_execution": requested_policy.execution.model_dump(exclude_none=True)
            if requested_policy.execution is not None
            else {},
            "resolved_execution": resolved_execution.model_dump(exclude_none=True),
            "effective_policy": next_policy.to_json_dict(),
            "resolved_at": datetime.now(UTC).isoformat(),
            "revision": int(current_snapshot.get("revision") or 1) + 1,
        }
        payload: dict[str, Any] = {
            "additional_iterations": additional_iterations,
            "effective_policy": next_policy.to_json_dict(),
            "governance_snapshot": next_snapshot,
        }
        if additional_budget_usd is not None:
            payload["additional_budget_usd"] = serialize_money(additional_budget_usd)
        return await self.workflow_service.continue_execution(task.execution_id, payload)

    async def _enrich_task_with_workflow_status(self, task: AgentTask) -> AgentTask:
        """Enrich a task with current workflow status.

        Temporal is the recovery oracle for terminal states; the DB is the
        source of truth otherwise. The workflow may stay alive in
        await_follow_up after writing "completed" to the DB, so a live
        Temporal "running" status must not overwrite a persisted DB status.

        Args:
            task: The task to enrich

        Returns:
            Task with status upgraded to terminal if Temporal reports one
        """
        if not task.execution_id or not self.workflow_service:
            return task

        try:
            workflow_status = await self.workflow_service.get_workflow_status(task.execution_id)
            wf_state = workflow_status.get("status")
            if wf_state in _TERMINAL_WORKFLOW_STATUSES:
                task.status = wf_state
                if workflow_status.get("result"):
                    task.result = workflow_status.get("result")
                if workflow_status.get("error"):
                    task.error_message = str(workflow_status["error"])
        except Exception as e:
            logger.debug(f"Could not get workflow status for task {task.id}: {e}")

        return task

    async def create_and_execute_task_with_workflow(
        self,
        agent_id: UUID,
        description: str,
        workspace_id: str,
        parameters: dict[str, Any] | None = None,
        user_id: str | None = None,
        requires_human_approval: bool = False,
        *,
        task_id: UUID | None = None,
        title: str | None = None,
        query: str | None = None,
        metadata_overrides: dict[str, Any] | None = None,
        status: str = "pending",
        task_policy: PolicyDocument | None = None,
    ) -> AgentTask:
        """Canonical entry point for creating and executing a task via Temporal workflow.

        REST handlers, A2A handlers, and MCP tools all funnel through this
        method (directly or via ``submit_task``) so behaviour stays consistent.

        Args:
            agent_id: The agent to execute the task
            description: Task description (used as default for title/query)
            workspace_id: Workspace ID (required for multi-tenancy isolation)
            parameters: Task parameters (channel_origin.chat_id triggers routing)
            user_id: User ID
            requires_human_approval: Whether to gate the task on human approval
            task_id: Pre-assign the task id (A2A echoes it back in JSON-RPC reply)
            title: Override the default title (defaults to ``description``)
            query: Override the default query string (defaults to ``description``)
            metadata_overrides: Caller metadata merged on top of canonical defaults.
            status: Initial task status (default ``pending``)
            task_policy: Optional task-scoped policy that may only tighten higher scopes.

        Returns:
            Created task with workflow execution info, or the routed-into existing
            task when ``channel_origin.chat_id`` matches an active workflow.
        """
        new_task_id = task_id or uuid4()

        # Try routing to an active workflow first — if a follow-up matches an
        # existing channel session, we never persist a new task or resolve a
        # new effective policy. Routing only needs identity/message fields.
        channel_origin = (parameters or {}).get("channel_origin", {})
        chat_id = channel_origin.get("chat_id") if channel_origin else None
        if chat_id:
            draft = AgentTask(
                id=new_task_id,
                title=title or description,
                description=description,
                query=query or description,
                user_id=user_id or "",
                workspace_id=workspace_id or "",
                agent_id=agent_id,
                status=status,
                task_parameters=parameters or {},
            )
            routed = await self._try_route_to_active_workflow(draft, str(chat_id))
            if routed:
                return routed

        # Persist + resolve governance policy via the canonical persist-only path.
        # This is the execution dispatch path, so require the agent to have a
        # model to run with (follow-ups routed above reuse the live workflow's
        # model and never reach here).
        stored_task = await self.create_task_with_policy(
            agent_id=agent_id,
            description=description,
            workspace_id=workspace_id,
            parameters=parameters,
            user_id=user_id,
            requires_human_approval=requires_human_approval,
            task_id=new_task_id,
            title=title,
            query=query,
            metadata_overrides=metadata_overrides,
            status=status,
            task_policy=task_policy,
            require_model=True,
        )

        stored_task.status = "pending"

        try:
            executed_task = await self.task_manager.submit_task(stored_task)
            stored_task.status = executed_task.status
            stored_task.execution_id = executed_task.execution_id
            logger.info(
                f"Task {new_task_id} submitted successfully with status {executed_task.status}"
            )
        except Exception as e:
            logger.error(f"Failed to submit task: {e}")
            stored_task.status = "failed"
            stored_task.result = {"error": str(e), "error_type": "task_submission_failed"}

        return stored_task

    async def _get_historical_events(self, task_id: UUID) -> list[dict[str, Any]]:
        """Get historical events for a task from the database with proper session management."""
        try:
            from agentarea_common.config.database import get_database
            from sqlalchemy import text

            # Use proper database session management to avoid connection leaks
            db = get_database()

            async with db.get_db() as session:
                # Query historical events from database
                query = text("""
                    SELECT event_type, timestamp, data, metadata
                    FROM task_events
                    WHERE task_id = :task_id
                    ORDER BY timestamp ASC
                """)

                result = await session.execute(query, {"task_id": str(task_id)})
                rows = result.fetchall()

                # Convert database rows to event format
                historical_events = []
                for row in rows:
                    historical_events.append(
                        {
                            "event_type": row.event_type,
                            "timestamp": row.timestamp.isoformat(),
                            "data": dict(row.data) if row.data else {},
                        }
                    )

                logger.debug(
                    f"Retrieved {len(historical_events)} historical events for task {task_id}"
                )
                return historical_events

        except Exception as e:
            logger.error(f"Failed to get historical events for task {task_id}: {e}")
            # Return empty list on error to not break SSE streaming
            return []

    def _format_protocol_event(self, event: dict[str, Any]) -> dict[str, Any]:
        """Format event using protocol structure with rich data, no metadata pollution.

        This method formats events according to the BaseWorkflowEvent protocol structure,
        ensuring consistent format across all transport mechanisms (SSE, REST, WebSocket).
        """
        event_type = event.get("event_type", "unknown")
        data = event.get("data", {})

        # Create protocol-compliant event structure
        protocol_event = {
            "event_type": event_type,
            "event_id": data.get("event_id") or event.get("event_id") or str(uuid4()),
            "timestamp": event.get("timestamp", datetime.now(UTC).isoformat()),
            "data": {
                # Core workflow event data
                "task_id": data.get("task_id", ""),
                "agent_id": data.get("agent_id", ""),
                "execution_id": data.get("execution_id", ""),
                "iteration": data.get("iteration"),
                # Event-specific data (preserve all original data)
                **{
                    k: v
                    for k, v in data.items()
                    if k not in ["task_id", "agent_id", "execution_id", "iteration", "event_id"]
                },
            },
        }

        return protocol_event
