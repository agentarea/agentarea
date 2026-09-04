"""RunsToolset — start, monitor, and steer agent execution runs.

Tool method signatures are explicit kwargs (MCP-idiomatic flat wire schema)
but the source of truth for ``start`` is the Pydantic DTO ``RunCreate`` in
``agentarea_tasks.schemas.dto``. The contract test in
``tests/unit/test_mcp_rest_parity.py`` enforces parity between toolset
kwargs and DTO fields.

The control tools (pause/resume/input/command/escalation) mirror the REST
handlers in ``api/v1/agents_tasks.py``, with one difference that matters:
those routes carry an ``agent_id`` the caller owns, while these take only a
``run_id``. Each control tool therefore loads the run through the
workspace-scoped ``TaskService`` first — that repository filter is the
authorization boundary, so signalling before it would cross tenants.
"""

import json
from typing import Any
from uuid import UUID

from agentarea_agents_sdk.tools.decorator_tool import Toolset, tool_method
from agentarea_agents_sdk.tools.tool_definition import toolset
from agentarea_common.money import serialize_money
from agentarea_llm.application.model_instance_service import ModelInstanceService
from agentarea_llm.infrastructure.model_instance_repository import ModelInstanceRepository
from agentarea_tasks.infrastructure.repository import TaskEventRepository
from agentarea_tasks.schemas.dto import RunCreate
from agentarea_tasks.task_service import TaskService
from fastapi import HTTPException

from agentarea_api.api.deps.services import (
    _create_task_manager,
    get_temporal_workflow_service,
)
from agentarea_api.api.v1.agents_tasks import (
    ContinueTaskPayload,
    EscalationResolution,
    TaskCommandPayload,
    TaskInputSubmission,
    _resolve_model_info,
)

from .base import platform_context, platform_read_context

RUN_NOT_FOUND = json.dumps({"error": "Run not found"})


async def _build_task_service(repo_factory, event_broker) -> TaskService:
    """Build a TaskService bound to the request-scoped repo factory."""
    task_manager = await _create_task_manager(repo_factory)
    workflow_service = await get_temporal_workflow_service()
    return TaskService(
        repository_factory=repo_factory,
        event_broker=event_broker,
        task_manager=task_manager,
        workflow_service=workflow_service,
    )


def _execution_id(run_id: str) -> str:
    """Workflow id for a run, matching ``api/v1/agents_tasks.py``."""
    return f"task-{run_id}"


async def _model_switch_body(model_instance_id: str, session, user_ctx, broker, secret_mgr) -> dict:
    """Resolve a model instance into the payload change_model expects."""
    service = ModelInstanceService(
        repository=ModelInstanceRepository(session, user_ctx),
        event_broker=broker,
        secret_manager=secret_mgr,
    )
    return await _resolve_model_info(model_instance_id, service)


@toolset(
    namespace="agentarea/runs",
    display_name="Agent Runs",
    description="Start, monitor, and manage agent execution runs.",
    category="platform",
    plane="operate",
)
class RunsToolset(Toolset):
    """Start, list, get, and cancel agent runs."""

    @tool_method(effect="write")
    async def start(
        self,
        agent_id: str,
        description: str,
        parameters: dict[str, Any] | None = None,
        requires_human_approval: bool = False,
        project_id: str | None = None,
        scheduled_at: str | None = None,
    ) -> str:
        """Start a new agent run, now or once at a future moment.

        Routes through ``TaskService.start_run`` so REST, MCP and A2A share the
        same execution path (channel routing, metadata defaults, workflow
        submission). Kwargs mirror the ``RunCreate`` REST DTO.

        ``scheduled_at`` defers the run to an absolute time: ISO-8601 including
        a UTC offset, e.g. ``2026-09-01T09:00:00+03:00``. It must be in the
        future, and it fires exactly once. To have an agent run repeatedly,
        create a cron trigger instead.
        """
        payload = RunCreate.model_validate(
            {
                "agent_id": UUID(agent_id),
                "description": description,
                "parameters": parameters or {},
                "requires_human_approval": requires_human_approval,
                "project_id": project_id,
                "scheduled_at": scheduled_at,
            }
        )

        async with platform_context() as (
            _session,
            user_ctx,
            repo_factory,
            event_broker,
            _,
        ):
            service = await _build_task_service(repo_factory, event_broker)
            submitted = await service.start_run(
                payload,
                workspace_id=user_ctx.workspace_id,
                user_id=user_ctx.user_id,
                created_via="mcp",
            )
            return json.dumps(
                {
                    "run_id": str(submitted.id),
                    "status": submitted.status,
                    "scheduled_at": submitted.scheduled_at,
                },
                default=str,
            )

    @tool_method(effect="read")
    async def list(self, agent_id: str = "", limit: int = 20) -> str:
        """List recent runs, optionally filtered by agent ID."""
        async with platform_read_context() as (
            _session,
            user_ctx,
            repo_factory,
            event_broker,
            _,
        ):
            service = await _build_task_service(repo_factory, event_broker)
            tasks = await service.list_tasks(user_id=user_ctx.user_id, limit=limit)
            return json.dumps(
                [
                    {
                        "run_id": str(t.id),
                        "title": t.title,
                        "status": t.status,
                        "agent_id": str(t.agent_id) if t.agent_id else None,
                    }
                    for t in tasks
                ],
                default=str,
            )

    @tool_method(effect="read")
    async def get(self, run_id: str) -> str:
        """Get status and details of a specific run."""
        async with platform_read_context() as (
            _session,
            _user_ctx,
            repo_factory,
            event_broker,
            _,
        ):
            service = await _build_task_service(repo_factory, event_broker)
            task = await service.get_task(UUID(run_id))
            if not task:
                return json.dumps({"error": "Run not found"})
            return json.dumps(
                {
                    "run_id": str(task.id),
                    "title": task.title,
                    "status": task.status,
                    "agent_id": str(task.agent_id) if task.agent_id else None,
                    "query": task.query,
                },
                default=str,
            )

    @tool_method(effect="destructive")
    async def cancel(self, run_id: str) -> str:
        """Cancel a running agent execution."""
        async with platform_context() as (
            _session,
            _user_ctx,
            repo_factory,
            event_broker,
            _,
        ):
            service = await _build_task_service(repo_factory, event_broker)
            cancelled = await service.cancel_task(UUID(run_id))
            return json.dumps({"cancelled": cancelled})

    @tool_method(effect="write")
    async def pause(self, run_id: str) -> str:
        """Pause a running agent execution."""
        async with platform_context() as (_s, _user_ctx, repo_factory, event_broker, _):
            service = await _build_task_service(repo_factory, event_broker)
            if not await service.get_task(UUID(run_id)):
                return RUN_NOT_FOUND
            workflow = await get_temporal_workflow_service()
            paused = await workflow.pause_task(_execution_id(run_id))
            return json.dumps({"paused": paused})

    @tool_method(effect="write")
    async def resume(self, run_id: str) -> str:
        """Resume a paused agent execution."""
        async with platform_context() as (_s, _user_ctx, repo_factory, event_broker, _):
            service = await _build_task_service(repo_factory, event_broker)
            if not await service.get_task(UUID(run_id)):
                return RUN_NOT_FOUND
            workflow = await get_temporal_workflow_service()
            resumed = await workflow.resume_task(_execution_id(run_id))
            return json.dumps({"resumed": resumed})

    @tool_method(effect="write")
    async def send_input(
        self,
        run_id: str,
        input_request_id: str,
        answers: dict[str, Any] | None = None,
    ) -> str:
        """Answer a run that is waiting on request_user_input.

        Secret-valued answers are deliberately not accepted here: the REST
        endpoint writes them to the workspace secret manager, and a secret
        should be created with ``secrets_create`` and referenced, not pasted
        through a tool call.
        """
        submission = TaskInputSubmission(
            input_request_id=input_request_id,
            answers=answers or {},
        )
        async with platform_context() as (_s, user_ctx, repo_factory, event_broker, _):
            service = await _build_task_service(repo_factory, event_broker)
            if not await service.get_task(UUID(run_id)):
                return RUN_NOT_FOUND
            workflow = await get_temporal_workflow_service()
            delivered = await workflow.send_workflow_command(
                _execution_id(run_id),
                "submit_user_input",
                {
                    "input_request_id": submission.input_request_id,
                    "answers": submission.answers,
                    "secret_refs": {},
                    "submitted_by": str(user_ctx.user_id),
                },
            )
            return json.dumps(
                {"delivered": delivered, "input_request_id": submission.input_request_id}
            )

    @tool_method(effect="write")
    async def send_command(
        self,
        run_id: str,
        command: str,
        message: str | None = None,
        message_id: str | None = None,
        model_instance_id: str | None = None,
        budget_usd: str | None = None,
    ) -> str:
        """Steer a running execution: queue_message, remove_message, change_model, update_budget."""
        payload = TaskCommandPayload.model_validate(
            {
                "command": command,
                "message": message,
                "message_id": message_id,
                "model_instance_id": model_instance_id,
                "budget_usd": budget_usd,
            }
        )
        async with platform_context() as (
            session,
            user_ctx,
            repo_factory,
            event_broker,
            secret_mgr,
        ):
            service = await _build_task_service(repo_factory, event_broker)
            if not await service.get_task(UUID(run_id)):
                return RUN_NOT_FOUND

            if payload.command == "queue_message":
                if not payload.message:
                    return json.dumps({"error": "message is required for queue_message"})
                body: dict[str, Any] = {"message": payload.message}
            elif payload.command == "remove_message":
                if not payload.message_id:
                    return json.dumps({"error": "message_id is required for remove_message"})
                body = {"message_id": payload.message_id}
            elif payload.command == "update_budget":
                if payload.budget_usd is None:
                    return json.dumps({"error": "budget_usd is required for update_budget"})
                body = {"budget_usd": serialize_money(payload.budget_usd)}
            elif payload.command == "change_model":
                if not payload.model_instance_id:
                    return json.dumps({"error": "model_instance_id is required for change_model"})
                try:
                    body = await _model_switch_body(
                        payload.model_instance_id, session, user_ctx, event_broker, secret_mgr
                    )
                except HTTPException as exc:
                    return json.dumps({"error": exc.detail})
            else:
                return json.dumps({"error": f"Unknown command: {payload.command}"})

            workflow = await get_temporal_workflow_service()
            delivered = await workflow.send_workflow_command(
                _execution_id(run_id), payload.command, body
            )
            return json.dumps({"delivered": delivered, "command": payload.command}, default=str)

    @tool_method(effect="privileged")
    async def resolve_escalation(
        self,
        run_id: str,
        escalation_id: str,
        approved: bool,
        comment: str = "",
    ) -> str:
        """Approve or deny a tool escalation a run is blocked on."""
        resolution = EscalationResolution(
            escalation_id=escalation_id, approved=approved, comment=comment
        )
        async with platform_context() as (_s, user_ctx, repo_factory, event_broker, _):
            service = await _build_task_service(repo_factory, event_broker)
            if not await service.get_task(UUID(run_id)):
                return RUN_NOT_FOUND
            workflow = await get_temporal_workflow_service()
            resolved = await workflow.resolve_escalation(
                _execution_id(run_id),
                resolution.escalation_id,
                resolution.approved,
                resolution.comment,
                resolved_by=str(user_ctx.user_id),
            )
            return json.dumps({"resolved": resolved, "approved": resolution.approved})

    @tool_method(effect="privileged")
    async def continue_run(
        self,
        run_id: str,
        additional_iterations: int = 0,
        additional_budget_usd: str | None = None,
    ) -> str:
        """Grant more iterations or budget to a run waiting for continuation."""
        payload = ContinueTaskPayload.model_validate(
            {
                "additional_iterations": additional_iterations,
                "additional_budget_usd": additional_budget_usd,
            }
        )
        async with platform_context() as (_s, _user_ctx, repo_factory, event_broker, _):
            service = await _build_task_service(repo_factory, event_broker)
            result = await service.continue_execution(
                UUID(run_id),
                additional_iterations=payload.additional_iterations,
                additional_budget_usd=payload.additional_budget_usd,
            )
            return json.dumps(result, default=str)

    @tool_method(effect="read")
    async def get_events(
        self,
        run_id: str,
        limit: int = 50,
        offset: int = 0,
        event_type: str | None = None,
    ) -> str:
        """Read a run's persisted execution events, newest page first."""
        async with platform_read_context() as (_s, _user_ctx, repo_factory, _broker, _):
            event_repository = repo_factory.create_repository(TaskEventRepository)
            records, total = await event_repository.list_for_task(
                UUID(run_id), event_type=event_type, limit=limit, offset=offset
            )
            return json.dumps(
                {
                    "total": total,
                    "events": [
                        {
                            "id": str(r.id),
                            "event_type": r.event_type,
                            "timestamp": r.timestamp,
                            "message": (r.data or {}).get("message"),
                        }
                        for r in records
                    ],
                },
                default=str,
            )
