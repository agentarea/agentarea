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
workspace-scoped ``TaskService`` first — signalling before that filter would
cross tenants — and then applies the same run authority as the REST routes:
only whoever started the run, or a workspace admin, may act on it.
"""

import json
from typing import Annotated, Any, Literal
from uuid import UUID

from agentarea_agents.application.execution_service import (
    EscalationNotPendingError,
    NotAnApproverError,
    WorkflowNotFoundError,
)
from agentarea_agents_sdk.tools.base_tool import ToolError
from agentarea_agents_sdk.tools.decorator_tool import Toolset, tool_method
from agentarea_agents_sdk.tools.tool_authz import enforced_in_handler, unrestricted
from agentarea_agents_sdk.tools.tool_definition import toolset
from agentarea_common.auth.context import UserContext
from agentarea_common.money import serialize_money
from agentarea_llm.application.model_instance_service import ModelInstanceService
from agentarea_llm.infrastructure.model_instance_repository import ModelInstanceRepository
from agentarea_tasks.domain.exceptions import BudgetCapExceededError, RunStillClosingError
from agentarea_tasks.domain.models import TaskProvenance
from agentarea_tasks.infrastructure.repository import TaskEventRepository, TaskRepository
from agentarea_tasks.schemas.dto import RunCreate
from agentarea_tasks.task_service import TaskService
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from agentarea_api.api.deps.services import (
    _create_task_manager,
    get_temporal_workflow_service,
)
from agentarea_api.api.v1._task_authority import assert_may_act_on_task
from agentarea_api.api.v1.agents_tasks import (
    ContinueTaskPayload,
    EscalationResolution,
    PendingEscalationResponse,
    TaskCommandPayload,
    TaskInputSubmission,
    _resolve_model_info,
    escalations_caller_may_resolve,
)

from .base import platform_context, platform_read_context

RUN_NOT_FOUND = "Run not found"
RUN_STILL_CLOSING = "The run is still stopping; try again in a few seconds"
RUN_AUTHORITY = "whoever started the run, or a workspace admin; _ensure_may_act loads the run first"

_FAILURE_FIELDS = (
    "error",
    "error_type",
    "failure_reason",
    "error_detail",
    "blocked_reason",
    "model_id",
)
_TERMINAL_FIELDS = ("status", "success", "error", "error_type", "failure_reason", "blocked_reason")
_TERMINAL_TYPES = {"task.completed", "task.failed", "task.cancelled", "execution.finished"}
_TOOL_RESULT_FIELDS = ("tool_name", "tool_call_id", "success", "replayed", "error", "exit_code")
_MODEL_CALL_FIELDS = ("model_id", "model_name", "cost", "provider_cost_usd")
_INPUT_REQUEST_FIELDS = (
    "input_request_id",
    "tool_call_id",
    "question",
    "questions",
    "allow_custom_response",
    "input_mode",
)
_INPUT_RESPONSE_FIELDS = ("input_request_id", "tool_call_id", "answer_keys", "secret_keys")

RunId = Annotated[str, Field(description="Run id, from `runs_list` or `runs_start`.")]


class RunStarted(BaseModel):
    run_id: str = Field(description="Id of the new run.")
    status: str = Field(description="Status the run was submitted with.")
    scheduled_at: str | None = Field(
        description="When a deferred run fires, with its UTC offset; null for a run started now."
    )


class RunSummary(BaseModel):
    run_id: str = Field(description="Run id.")
    title: str = Field(description="Run title.")
    status: str = Field(description="Run status, e.g. running, completed, failed.")
    agent_id: str | None = Field(description="Agent executing the run.")


class RunDetail(RunSummary):
    query: str = Field(description="The message the run was started with.")
    provenance: TaskProvenance = Field(description="Who or what started the run, and why.")


class RunCancelled(BaseModel):
    cancelled: bool = Field(description="Whether the run's execution was cancelled.")


class RunRetried(BaseModel):
    retried: bool = Field(description="Always true; a run that cannot be retried is an error.")
    run_id: str = Field(description="The run being retried.")


class RunPaused(BaseModel):
    paused: bool = Field(description="Whether the pause reached the running execution.")


class RunResumed(BaseModel):
    resumed: bool = Field(description="Whether the resume reached the paused execution.")


class InputDelivered(BaseModel):
    delivered: bool = Field(description="Whether the answers reached the running execution.")
    input_request_id: str = Field(description="The input request answered.")


class CommandDelivered(BaseModel):
    delivered: bool = Field(description="Whether the command reached the run.")
    command: str = Field(description="The command sent.")


class EscalationResolved(BaseModel):
    resolved: bool = Field(description="Whether the decision reached the run.")
    approved: bool = Field(description="The decision sent: true approves, false denies.")


class ContinuationResult(BaseModel):
    accepted: bool = Field(description="Whether the run took the grant and continues.")
    reason: str | None = Field(
        default=None,
        description="Why the grant was refused, e.g. not_waiting_for_continuation, "
        "policy_ceiling, additional_budget_required; absent when accepted.",
    )
    continuation_count: int | None = Field(
        default=None, description="How many times the run has been continued, when accepted."
    )
    max_iterations: int | None = Field(
        default=None, description="The run's new iteration limit, when accepted."
    )
    budget_usd: str | None = Field(
        default=None, description="The run's new budget in USD, decimal string, when accepted."
    )


class RunEvent(BaseModel):
    """One persisted event, with the facts its type carries as further keys."""

    model_config = ConfigDict(extra="allow")

    id: str = Field(description="Event id.")
    event_type: str = Field(description="Event type, e.g. tool.call, task.failed.")
    timestamp: str = Field(description="When the event happened.")
    message: str | None = Field(default=None, description="Human-readable summary, when set.")
    input_request_id: str | None = Field(
        default=None,
        description="On input.request and input.response: the id `runs_send_input` answers.",
    )
    questions: list[dict[str, Any]] | None = Field(
        default=None,
        description="On input.request: each question's id (the key of its answer), "
        "question, type, whether it is required, and its options when it has them.",
    )


PendingEscalations = list[PendingEscalationResponse]


class RunEventsPage(BaseModel):
    total: int = Field(description="Events matching the filter across all pages.")
    events: list[RunEvent] = Field(description="Events on this page, oldest first.")


def _event_projection(event_type: str, data: dict[str, Any]) -> dict[str, Any]:
    """The facts of one event worth reading over MCP, without results or content."""
    fields: tuple[str, ...] = ()
    extra: dict[str, Any] = {}
    if event_type in _TERMINAL_TYPES or event_type.startswith("task.awaiting_"):
        fields = _TERMINAL_FIELDS
    elif event_type.endswith(".failed"):
        fields = _FAILURE_FIELDS
    elif event_type == "tool.call":
        fields = ("tool_name", "tool_call_id")
        arguments = data.get("arguments")
        if isinstance(arguments, dict) and arguments:
            extra["argument_names"] = list(arguments)
    elif event_type == "tool.result":
        fields = _TOOL_RESULT_FIELDS
    elif event_type == "input.request":
        fields = _INPUT_REQUEST_FIELDS
    elif event_type == "input.response":
        fields = _INPUT_RESPONSE_FIELDS
    elif event_type == "llm.call.completed":
        fields = _MODEL_CALL_FIELDS
        usage = (data.get("usage") or {}).get("usage")
        if isinstance(usage, dict) and usage:
            extra["usage"] = usage
    projection = {key: data[key] for key in ("message", *fields) if data.get(key) is not None}
    return projection | extra


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


async def _ensure_may_act(service: TaskService, run_id: str, user_ctx: UserContext) -> None:
    """Refuse unless the caller started this run or administers the workspace."""
    task = await service.get_task(UUID(run_id))
    if not task:
        raise ToolError(RUN_NOT_FOUND)
    try:
        await assert_may_act_on_task(task, user_ctx)
    except HTTPException as exc:
        raise ToolError(exc.detail) from exc


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

    open_world = False

    @tool_method(display_name="Start run", effect="write", output=RunStarted)
    @unrestricted("any member may start a run, as POST /v1/agents/{id}/tasks allows")
    async def start(
        self,
        agent_id: Annotated[str, Field(description="Agent id (UUID), from `agents_list`.")],
        description: Annotated[
            str,
            Field(
                description="The message handed to the agent, 1-20000 characters; also the "
                "run title."
            ),
        ],
        parameters: Annotated[
            dict[str, Any] | None,
            Field(
                description='Free-form task parameters, e.g. {"model_override": "<model id>"} '
                "plus any agent-specific context. channel_origin is reserved and rejected."
            ),
        ] = None,
        requires_human_approval: Annotated[
            bool, Field(description="Hold the run for a person's approval before tool calls.")
        ] = False,
        project_id: Annotated[
            str | None, Field(description="Project id to scope the run to, from `projects_list`.")
        ] = None,
        scheduled_at: Annotated[
            str | None,
            Field(
                description="Run once at this future time instead of now: ISO 8601 with a UTC "
                "offset, e.g. 2026-09-01T09:00:00+03:00."
            ),
        ] = None,
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
            try:
                submitted = await service.start_run(
                    payload,
                    workspace_id=user_ctx.workspace_id,
                    user_id=user_ctx.user_id,
                    created_via="mcp",
                )
            except BudgetCapExceededError as exc:
                raise ToolError(str(exc)) from None
            return json.dumps(
                {
                    "run_id": str(submitted.id),
                    "status": submitted.status,
                    "scheduled_at": submitted.scheduled_at,
                },
                default=str,
            )

    @tool_method(display_name="List runs", effect="read", output=list[RunSummary])
    @unrestricted("the workspace's runs, as GET /v1/tasks lists them")
    async def list(
        self,
        agent_id: Annotated[
            str, Field(description="Only runs of this agent id, from `agents_list`; empty for any.")
        ] = "",
        limit: Annotated[int, Field(description="Most runs to return, newest first.")] = 20,
    ) -> str:
        """List the workspace's recent runs, newest first, optionally filtered by agent ID."""
        async with platform_read_context() as (_s, _user_ctx, repo_factory, _broker, _):
            records = await repo_factory.create_repository(TaskRepository).list_page(
                limit=limit,
                offset=0,
                agent_id=UUID(agent_id) if agent_id else None,
            )
            return json.dumps(
                [
                    {
                        "run_id": str(r.id),
                        "title": r.description,
                        "status": r.status,
                        "agent_id": str(r.agent_id) if r.agent_id else None,
                    }
                    for r in records
                ]
            )

    @tool_method(display_name="Get run", effect="read", output=RunDetail)
    @unrestricted("a run in the caller's workspace, as GET /v1/tasks/{id} returns it")
    async def get(self, run_id: RunId) -> str:
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
                raise ToolError("Run not found")
            return json.dumps(
                {
                    "run_id": str(task.id),
                    "title": task.title,
                    "status": task.status,
                    "agent_id": str(task.agent_id) if task.agent_id else None,
                    "query": task.query,
                    "provenance": task.provenance.model_dump(mode="json"),
                },
                default=str,
            )

    @tool_method(
        display_name="Cancel run", effect="destructive", idempotent=True, output=RunCancelled
    )
    @enforced_in_handler(RUN_AUTHORITY)
    async def cancel(self, run_id: RunId) -> str:
        """Cancel a running agent execution."""
        async with platform_context() as (
            _session,
            user_ctx,
            repo_factory,
            event_broker,
            _,
        ):
            service = await _build_task_service(repo_factory, event_broker)
            await _ensure_may_act(service, run_id, user_ctx)
            cancelled = await service.cancel_task(UUID(run_id))
            return json.dumps({"cancelled": cancelled})

    @tool_method(display_name="Retry failed run", effect="write", output=RunRetried)
    @enforced_in_handler(RUN_AUTHORITY)
    async def retry(self, run_id: RunId) -> str:
        """Re-run the turn a failed run ended on, on the same conversation, with no new message."""
        async with platform_context() as (_s, user_ctx, repo_factory, event_broker, _):
            service = await _build_task_service(repo_factory, event_broker)
            await _ensure_may_act(service, run_id, user_ctx)
            try:
                retried = await service.retry_last_turn(UUID(run_id))
            except RunStillClosingError:
                raise ToolError(RUN_STILL_CLOSING) from None
            if not retried:
                raise ToolError("Only a failed run whose execution has finished can be retried")
            return json.dumps({"retried": True, "run_id": run_id})

    @tool_method(display_name="Pause run", effect="write", idempotent=True, output=RunPaused)
    @enforced_in_handler(RUN_AUTHORITY)
    async def pause(self, run_id: RunId) -> str:
        """Pause a running agent execution."""
        async with platform_context() as (_s, user_ctx, repo_factory, event_broker, _):
            service = await _build_task_service(repo_factory, event_broker)
            await _ensure_may_act(service, run_id, user_ctx)
            workflow = await get_temporal_workflow_service()
            paused = await workflow.pause_task(_execution_id(run_id))
            return json.dumps({"paused": paused})

    @tool_method(display_name="Resume run", effect="write", idempotent=True, output=RunResumed)
    @enforced_in_handler(RUN_AUTHORITY)
    async def resume(self, run_id: RunId) -> str:
        """Resume a paused agent execution."""
        async with platform_context() as (_s, user_ctx, repo_factory, event_broker, _):
            service = await _build_task_service(repo_factory, event_broker)
            await _ensure_may_act(service, run_id, user_ctx)
            workflow = await get_temporal_workflow_service()
            resumed = await workflow.resume_task(_execution_id(run_id))
            return json.dumps({"resumed": resumed})

    @tool_method(display_name="Answer run input request", effect="write", output=InputDelivered)
    @enforced_in_handler(RUN_AUTHORITY)
    async def send_input(
        self,
        run_id: RunId,
        input_request_id: Annotated[
            str,
            Field(
                description="Id of the pending request, from the run's input.request event; "
                "1-128 characters."
            ),
        ],
        answers: Annotated[
            dict[str, Any] | None,
            Field(
                description="Answers keyed by the question ids of the request, e.g. "
                '{"<question id>": "yes"}. Secret answers are not accepted.'
            ),
        ] = None,
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
            await _ensure_may_act(service, run_id, user_ctx)
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

    @tool_method(display_name="Send run command", effect="write", output=CommandDelivered)
    @enforced_in_handler(RUN_AUTHORITY)
    async def send_command(
        self,
        run_id: RunId,
        command: Annotated[
            Literal["queue_message", "remove_message", "change_model", "update_budget"],
            Field(
                description="What to do: queue_message takes `message`, remove_message "
                "`message_id`, change_model `model_instance_id`, update_budget `budget_usd`."
            ),
        ],
        message: Annotated[
            str | None,
            Field(
                description="For queue_message: the message for the agent's next turn. A "
                "finished run continues its conversation with it."
            ),
        ] = None,
        message_id: Annotated[
            str | None,
            Field(description="For remove_message: id of a queued message to drop."),
        ] = None,
        model_instance_id: Annotated[
            str | None,
            Field(description="For change_model: model instance id, from `models_list_instances`."),
        ] = None,
        budget_usd: Annotated[
            str | None,
            Field(description='For update_budget: the run\'s new budget in USD, e.g. "5.00".'),
        ] = None,
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
            await _ensure_may_act(service, run_id, user_ctx)

            if payload.command == "queue_message":
                if not payload.message:
                    raise ToolError("message is required for queue_message")
                body: dict[str, Any] = {"message": payload.message}
            elif payload.command == "remove_message":
                if not payload.message_id:
                    raise ToolError("message_id is required for remove_message")
                body = {"message_id": payload.message_id}
            elif payload.command == "update_budget":
                if payload.budget_usd is None:
                    raise ToolError("budget_usd is required for update_budget")
                body = {"budget_usd": serialize_money(payload.budget_usd)}
            elif payload.command == "change_model":
                if not payload.model_instance_id:
                    raise ToolError("model_instance_id is required for change_model")
                try:
                    body = await _model_switch_body(
                        payload.model_instance_id, session, user_ctx, event_broker, secret_mgr
                    )
                except HTTPException as exc:
                    raise ToolError(exc.detail) from exc
            else:
                raise ToolError(f"Unknown command: {payload.command}")

            if payload.command == "queue_message":
                # A completed, stopped or failed run whose execution has closed
                # continues its conversation in a new execution.
                try:
                    delivered = await service.queue_follow_up(UUID(run_id), body["message"])
                except RunStillClosingError:
                    raise ToolError(RUN_STILL_CLOSING) from None
            else:
                workflow = await get_temporal_workflow_service()
                delivered = await workflow.send_workflow_command(
                    _execution_id(run_id), payload.command, body
                )
            return json.dumps({"delivered": delivered, "command": payload.command}, default=str)

    @tool_method(
        display_name="Resolve run escalation",
        effect="privileged",
        idempotent=True,
        output=EscalationResolved,
    )
    @enforced_in_handler(RUN_AUTHORITY)
    async def resolve_escalation(
        self,
        run_id: RunId,
        escalation_id: Annotated[
            str,
            Field(description="Escalation id, from `runs_list_pending_escalations`."),
        ],
        approved: Annotated[
            bool, Field(description="True runs the held tool call; false denies it.")
        ],
        comment: Annotated[
            str, Field(description="Note recorded with the decision; may be empty.")
        ] = "",
    ) -> str:
        """Approve or deny a tool escalation a run is blocked on."""
        resolution = EscalationResolution(
            escalation_id=escalation_id, approved=approved, comment=comment
        )
        async with platform_context() as (_s, user_ctx, repo_factory, event_broker, _):
            service = await _build_task_service(repo_factory, event_broker)
            await _ensure_may_act(service, run_id, user_ctx)
            workflow = await get_temporal_workflow_service()
            try:
                resolved = await workflow.resolve_escalation(
                    _execution_id(run_id),
                    resolution.escalation_id,
                    resolution.approved,
                    resolution.comment,
                    resolved_by=str(user_ctx.user_id),
                )
            except EscalationNotPendingError:
                raise ToolError("Escalation not found or no longer pending") from None
            except NotAnApproverError:
                raise ToolError("You are not an approver of this escalation") from None
            return json.dumps({"resolved": resolved, "approved": resolution.approved})

    @tool_method(
        display_name="List pending escalations",
        effect="read",
        output=PendingEscalations,
    )
    @enforced_in_handler(RUN_AUTHORITY)
    async def list_pending_escalations(self, run_id: RunId) -> str:
        """List the escalations a run is blocked on that you may resolve.

        Each carries the exact tool arguments awaiting a decision. Run events
        redact them, since a command can carry an inline secret, so only a
        caller who may act on the run and is one of the escalation's approvers
        sees them.
        """
        async with platform_context() as (_s, user_ctx, repo_factory, event_broker, _):
            service = await _build_task_service(repo_factory, event_broker)
            await _ensure_may_act(service, run_id, user_ctx)
            workflow = await get_temporal_workflow_service()
            try:
                pending = await workflow.get_pending_escalations(_execution_id(run_id))
            except WorkflowNotFoundError:
                raise ToolError("Run has no workflow to read escalations from") from None
            return json.dumps(
                [
                    escalation.model_dump()
                    for escalation in escalations_caller_may_resolve(pending, str(user_ctx.user_id))
                ]
            )

    @tool_method(display_name="Continue run", effect="privileged", output=ContinuationResult)
    @enforced_in_handler(RUN_AUTHORITY)
    async def continue_run(
        self,
        run_id: RunId,
        additional_iterations: Annotated[
            int, Field(description="Extra model turns to grant, 0-1000.")
        ] = 0,
        additional_budget_usd: Annotated[
            str | None,
            Field(description='Extra budget in USD, a positive decimal string, e.g. "2.50".'),
        ] = None,
        additional_tokens: Annotated[
            int, Field(description="Extra tokens to grant, 0-10000000.")
        ] = 0,
        additional_tool_calls: Annotated[
            int, Field(description="Extra tool calls to grant, 0-10000.")
        ] = 0,
    ) -> str:
        """Grant more iterations, budget, tokens or tool calls to a run waiting for continuation."""
        payload = ContinueTaskPayload.model_validate(
            {
                "additional_iterations": additional_iterations,
                "additional_budget_usd": additional_budget_usd,
                "additional_tokens": additional_tokens,
                "additional_tool_calls": additional_tool_calls,
            }
        )
        async with platform_context() as (_s, user_ctx, repo_factory, event_broker, _):
            service = await _build_task_service(repo_factory, event_broker)
            await _ensure_may_act(service, run_id, user_ctx)
            result = await service.continue_execution(
                UUID(run_id),
                additional_iterations=payload.additional_iterations,
                additional_budget_usd=payload.additional_budget_usd,
                additional_tokens=payload.additional_tokens,
                additional_tool_calls=payload.additional_tool_calls,
            )
            return json.dumps(result, default=str)

    @tool_method(display_name="Get run events", effect="read", output=RunEventsPage)
    @unrestricted("persisted run events, as GET /v1/agents/{id}/tasks/{id}/events serves them")
    async def get_events(
        self,
        run_id: RunId,
        limit: Annotated[int, Field(description="Most events to return.")] = 50,
        offset: Annotated[
            int, Field(description="Events to skip from the oldest; total-limit reads the latest.")
        ] = 0,
        event_type: Annotated[
            str | None,
            Field(description="Only events of this type, e.g. tool.result or task.failed."),
        ] = None,
    ) -> str:
        """Read a run's persisted execution events, oldest first.

        Each event carries the facts of its type: the error of a failure, the
        outcome of a tool call, the cost and token usage of a model call, the
        status of a terminal event. For the latest events, page from
        offset=total-limit.
        """
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
                            **_event_projection(r.event_type, r.data or {}),
                        }
                        for r in records
                    ],
                },
                default=str,
            )
