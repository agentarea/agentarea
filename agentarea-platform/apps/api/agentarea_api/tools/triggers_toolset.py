"""TriggersToolset — manage cron, webhook and stream triggers.

Tool method signatures are explicit kwargs (MCP-idiomatic flat wire schema)
but the source of truth for ``create_cron``/``create_webhook``/``create_stream`` is the
Pydantic DTO ``TriggerCreate`` in ``agentarea_triggers.schemas.dto``. The
contract test in ``tests/unit/test_mcp_rest_parity.py`` enforces parity
between toolset kwargs and DTO fields.
"""

import builtins
import json
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from agentarea_agents_sdk.tools.base_tool import ToolError
from agentarea_agents_sdk.tools.decorator_tool import Toolset, tool_method
from agentarea_agents_sdk.tools.tool_authz import requires, unrestricted
from agentarea_agents_sdk.tools.tool_definition import toolset
from agentarea_streams.domain.models import TriggerBinding
from agentarea_triggers.domain.enums import ExecutionStatus
from agentarea_triggers.schemas.dto import TriggerCreate, TriggerTypeLiteral
from fastapi import HTTPException
from pydantic import BaseModel, Field

from ..api.v1._trigger_creation import public_webhook_url, require_stream_readable
from ..api.v1.triggers import TriggerStatus, trigger_status
from .base import platform_context, platform_read_context

TriggerId = Annotated[str, Field(description="Trigger id (UUID), from `triggers_list`.")]
AgentId = Annotated[
    str, Field(description="Id (UUID) of the agent the trigger runs, from `agents_list`.")
]
TriggerName = Annotated[str, Field(description="Trigger name; 1-255 characters.")]
TriggerDescription = Annotated[
    str, Field(description="What the trigger is for; up to 1000 characters.")
]
TaskParameters = Annotated[
    dict[str, Any] | None,
    Field(
        description=(
            'Merged into every task the trigger creates, as {"text": "<what the agent is '
            'asked to do>", ...}; other keys are passed along.'
        )
    ),
]
Conditions = Annotated[
    dict[str, Any] | None,
    Field(
        description=(
            "Checked against the event before firing; null fires always. An LLM condition "
            '{"type": "llm", "description": "...", "model_id": "<model instance id from '
            '`models_list_instances`>"} names the model that evaluates it.'
        )
    ),
]
Enabled = Annotated[
    bool, Field(description="Whether the trigger is active as soon as it is created.")
]
FailureThreshold = Annotated[
    int,
    Field(description="Consecutive failed runs, 1-100, after which the trigger disables itself."),
]


class TriggerSummaryOutput(BaseModel):
    id: str = Field(description="Trigger id (UUID).")
    name: str = Field(description="Trigger name.")
    description: str = Field(description="What the trigger is for.")
    agent_id: str = Field(description="Id (UUID) of the agent it runs.")
    trigger_type: TriggerTypeLiteral = Field(description="cron, webhook, polling or stream.")
    is_active: bool = Field(description="Whether it fires now.")
    cron_expression: str | None = Field(default=None, description="Schedule of a cron trigger.")
    webhook_id: str | None = Field(
        default=None, description="Path segment of a webhook trigger's URL."
    )
    status: TriggerStatus = Field(
        description="active, inactive, or needs_owner when it stopped for its owner's lost access."
    )
    needs_new_owner: bool = Field(description="True while status is needs_owner.")
    stream_id: str | None = Field(
        default=None, description="Id (UUID) of the stream it listens to or feeds."
    )
    event_filter: dict[str, Any] | None = Field(
        default=None, description="Which of the stream's events fire it; {} fires on all."
    )
    webhook_url: str | None = Field(default=None, description="Public URL senders post to.")
    last_event_at: datetime | None = Field(
        default=None, description="When an event last reached it."
    )


class TriggerDeletedOutput(BaseModel):
    deleted: bool = Field(description="False when no such trigger existed.")


class TriggerEnabledOutput(BaseModel):
    enabled: bool = Field(description="False when no such trigger existed.")


class TriggerDisabledOutput(BaseModel):
    disabled: bool = Field(description="False when no such trigger existed.")


class TriggerExecutionOutput(BaseModel):
    id: str = Field(description="Execution id (UUID).")
    status: ExecutionStatus = Field(description="How the firing ended.")
    executed_at: datetime | None = Field(default=None, description="When it fired.")
    execution_time_ms: int = Field(description="How long the firing took, in milliseconds.")
    error_message: str | None = Field(default=None, description="Why it failed, if it did.")
    task_id: str | None = Field(
        default=None, description="Id (UUID) of the task it started, for `runs_get`."
    )


async def _build_trigger_service(
    repo_factory: Any,
    event_broker: Any,
    secret_manager: Any,
):
    from agentarea_common.config import get_settings
    from agentarea_triggers.temporal_schedule_manager import TemporalScheduleManager
    from agentarea_triggers.trigger_service import TriggerService

    settings = get_settings()
    temporal_schedule_manager: TemporalScheduleManager | None = None
    try:
        temporal_schedule_manager = TemporalScheduleManager(
            task_queue=settings.triggers.QUEUE,
        )
    except Exception:
        temporal_schedule_manager = None

    return TriggerService(
        repository_factory=repo_factory,
        event_broker=event_broker,
        temporal_schedule_manager=temporal_schedule_manager,
        secret_manager=secret_manager,
    )


def _trigger_summary(trigger: Any, binding: TriggerBinding | None) -> dict[str, Any]:
    """A trigger as MCP returns it; the stream fields come from its subscription, as in REST."""
    status = trigger_status(trigger)
    return {
        "id": str(trigger.id),
        "name": trigger.name,
        "description": trigger.description,
        "agent_id": str(trigger.agent_id),
        "trigger_type": getattr(trigger.trigger_type, "value", str(trigger.trigger_type)),
        "is_active": trigger.is_active,
        "cron_expression": getattr(trigger, "cron_expression", None),
        "webhook_id": getattr(trigger, "webhook_id", None),
        "status": status,
        "needs_new_owner": status == "needs_owner",
        "stream_id": binding.stream_id if binding else None,
        "event_filter": binding.event_filter if binding else None,
        "webhook_url": (
            public_webhook_url(binding.webhook_id) if binding and binding.webhook_id else None
        ),
        "last_event_at": binding.last_event_at if binding else None,
    }


async def _summary(service: Any, trigger: Any) -> dict[str, Any]:
    bindings = await service.stream_service.trigger_bindings([trigger.id])
    return _trigger_summary(trigger, bindings.get(trigger.id))


@toolset(
    namespace="agentarea/triggers",
    display_name="Triggers",
    description="Schedule agents on cron expressions or wire them to webhooks.",
    category="platform",
    plane="build",
    # Shares namespace with TriggersAgentToolset (agent self-management). The
    # agent variant owns the registry lookup; this platform variant is exposed
    # only via ``get_platform_tools()`` for the /mcp surface, so we skip
    # registration to avoid the collision.
    register=False,
)
class TriggersToolset(Toolset):
    """Manage triggers: list, get, create cron/webhook/stream, delete, enable/disable, history."""

    open_world = False

    @tool_method(display_name="List triggers", effect="read", output=list[TriggerSummaryOutput])
    @unrestricted("triggers in the caller's workspace, as GET /v1/triggers lists them")
    async def list(
        self,
        agent_id: Annotated[
            str,
            Field(
                description="Only this agent's triggers (UUID, from `agents_list`); empty for all."
            ),
        ] = "",
        active_only: Annotated[bool, Field(description="Only triggers that fire now.")] = False,
        limit: Annotated[int, Field(description="Most triggers to return.")] = 100,
    ) -> str:
        """List triggers, optionally filtered by agent or active state."""
        async with platform_read_context() as (_session, _user_ctx, repo_factory, broker, secret):
            service = await _build_trigger_service(repo_factory, broker, secret)
            triggers = await service.list_triggers(
                agent_id=UUID(agent_id) if agent_id else None,
                active_only=active_only,
                limit=limit,
            )
            bindings = await service.stream_service.trigger_bindings([t.id for t in triggers])
            return json.dumps(
                [_trigger_summary(t, bindings.get(t.id)) for t in triggers], default=str
            )

    @tool_method(display_name="Get trigger", effect="read", output=TriggerSummaryOutput)
    @unrestricted("a trigger in the caller's workspace, as GET /v1/triggers/{id} returns it")
    async def get(self, trigger_id: TriggerId) -> str:
        """Get a trigger by ID."""
        async with platform_read_context() as (_session, _user_ctx, repo_factory, broker, secret):
            service = await _build_trigger_service(repo_factory, broker, secret)
            trigger = await service.get_trigger(UUID(trigger_id))
            if not trigger:
                raise ToolError("Trigger not found")
            return json.dumps(await _summary(service, trigger), default=str)

    @tool_method(display_name="Create cron trigger", effect="write", output=TriggerSummaryOutput)
    @unrestricted("any member may create a trigger, as POST /v1/triggers allows")
    async def create_cron(
        self,
        name: TriggerName,
        agent_id: AgentId,
        cron_expression: Annotated[
            str, Field(description="5- or 6-field cron expression, e.g. '0 9 * * 1-5'.")
        ],
        description: TriggerDescription = "",
        timezone: Annotated[
            str, Field(description="IANA timezone the expression is read in, e.g. 'Europe/Moscow'.")
        ] = "UTC",
        task_parameters: TaskParameters = None,
        conditions: Conditions = None,
        enabled: Enabled = True,
        failure_threshold: FailureThreshold = 5,
    ) -> str:
        """Create a cron-based trigger that fires the given agent on a schedule.

        ``cron_expression`` is a 5- or 6-field expression evaluated in
        ``timezone`` (default UTC). This always repeats — cron cannot express a
        year, so a "one-shot" cron fires again next year. For a single run at a
        given moment use ``runs_start`` with ``scheduled_at`` instead.

        ``task_parameters`` are merged into every task created when the trigger
        fires, and must carry ``text`` -- what the agent is asked to do each time.
        A schedule arrives carrying nothing, so there is no other source for it.
        ``conditions`` is an optional rule/LLM condition map evaluated against
        event data before firing.
        """
        async with platform_context() as (_session, user_ctx, repo_factory, broker, secret):
            service = await _build_trigger_service(repo_factory, broker, secret)
            payload = TriggerCreate(
                name=name,
                description=description,
                agent_id=UUID(agent_id),
                trigger_type="cron",
                cron_expression=cron_expression,
                timezone=timezone,
                task_parameters=task_parameters or {},
                conditions=conditions or {},
                enabled=enabled,
                failure_threshold=failure_threshold,
            )
            trigger = await service.create_trigger_from_payload(
                payload,
                created_by=user_ctx.user_id,
                workspace_id=user_ctx.workspace_id,
            )
            return json.dumps(await _summary(service, trigger), default=str)

    @tool_method(display_name="Create webhook trigger", effect="write", output=TriggerSummaryOutput)
    @unrestricted("any member may create a trigger, as POST /v1/triggers allows")
    async def create_webhook(
        self,
        name: TriggerName,
        agent_id: AgentId,
        webhook_id: Annotated[
            str,
            Field(
                description=(
                    "Path segment of the URL, at least 16 of A-Z a-z 0-9 _ -; empty to "
                    "have one generated."
                )
            ),
        ] = "",
        description: TriggerDescription = "",
        webhook_type: Annotated[
            str,
            Field(
                description="Channel the requests come from: 'generic', 'telegram', 'slack', 'github', ..."
            ),
        ] = "generic",
        allowed_methods: Annotated[
            builtins.list[str] | None,
            Field(description="HTTP methods the URL accepts; null for POST only."),
        ] = None,
        task_parameters: TaskParameters = None,
        conditions: Conditions = None,
        enabled: Enabled = True,
        failure_threshold: FailureThreshold = 5,
        event_types: Annotated[
            builtins.list[str] | None,
            Field(description="Channel event kinds that fire it, e.g. ['push']; null for all."),
        ] = None,
    ) -> str:
        """Create a webhook trigger. Inbound webhook URL becomes /webhooks/{webhook_id}.

        If ``webhook_id`` is empty, a URL-safe id is auto-generated server-side.
        ``webhook_type`` must be a registered channel ('generic', 'telegram',
        'slack', 'discord', 'github', etc.). ``event_types`` filters which
        channel events fire the trigger (empty = all events).
        """
        async with platform_context() as (_session, user_ctx, repo_factory, broker, secret):
            service = await _build_trigger_service(repo_factory, broker, secret)
            payload = TriggerCreate(
                name=name,
                description=description,
                agent_id=UUID(agent_id),
                trigger_type="webhook",
                webhook_id=webhook_id or None,
                webhook_type=webhook_type,
                allowed_methods=allowed_methods or ["POST"],
                task_parameters=task_parameters or {},
                conditions=conditions or {},
                enabled=enabled,
                failure_threshold=failure_threshold,
                event_types=event_types or [],
            )
            trigger = await service.create_trigger_from_payload(
                payload,
                created_by=user_ctx.user_id,
                workspace_id=user_ctx.workspace_id,
            )
            return json.dumps(await _summary(service, trigger), default=str)

    @tool_method(display_name="Create stream trigger", effect="write", output=TriggerSummaryOutput)
    @unrestricted("any member may create a trigger, as POST /v1/triggers allows")
    async def create_stream(
        self,
        name: TriggerName,
        agent_id: AgentId,
        stream_id: Annotated[
            str,
            Field(description="Id (UUID) of the stream whose events fire it, from `streams_list`."),
        ],
        description: TriggerDescription = "",
        event_filter: Annotated[
            dict[str, Any] | None,
            Field(
                description=(
                    'Which events fire it: {"kinds": [<event kind>, ...], "fields": '
                    "{<dotted path in the event data>: <value>}}; null or {} fires on all."
                )
            ),
        ] = None,
        task_parameters: TaskParameters = None,
        conditions: Conditions = None,
        enabled: Enabled = True,
        failure_threshold: FailureThreshold = 5,
    ) -> str:
        """Create a trigger that fires the agent on events of an existing stream.

        ``event_filter`` picks events: {"kinds": ["push"], "fields": {"raw_data.action":
        "opened"}}; empty fires on every event. Only events that arrive after the
        trigger is created fire it.
        """
        async with platform_context() as (_session, user_ctx, repo_factory, broker, secret):
            try:
                await require_stream_readable(UUID(stream_id), user_ctx.user_id)
            except HTTPException as exc:
                raise ToolError(exc.detail) from exc
            service = await _build_trigger_service(repo_factory, broker, secret)
            payload = TriggerCreate(
                name=name,
                description=description,
                agent_id=UUID(agent_id),
                trigger_type="stream",
                stream_id=UUID(stream_id),
                event_filter=event_filter,
                task_parameters=task_parameters or {},
                conditions=conditions or {},
                enabled=enabled,
                failure_threshold=failure_threshold,
            )
            trigger = await service.create_trigger_from_payload(
                payload,
                created_by=user_ctx.user_id,
                workspace_id=user_ctx.workspace_id,
            )
            return json.dumps(await _summary(service, trigger), default=str)

    @tool_method(
        display_name="Delete trigger",
        effect="destructive",
        idempotent=True,
        output=TriggerDeletedOutput,
    )
    @requires("delete", "trigger", id_param="trigger_id")
    async def delete(self, trigger_id: TriggerId) -> str:
        """Delete a trigger and its schedule."""
        async with platform_context() as (_session, _user_ctx, repo_factory, broker, secret):
            service = await _build_trigger_service(repo_factory, broker, secret)
            deleted = await service.delete_trigger(UUID(trigger_id))
            return json.dumps({"deleted": deleted})

    @tool_method(
        display_name="Enable trigger",
        effect="write",
        idempotent=True,
        output=TriggerEnabledOutput,
    )
    @requires("edit", "trigger", id_param="trigger_id")
    async def enable(self, trigger_id: TriggerId) -> str:
        """Enable a trigger (resumes its schedule for cron triggers)."""
        async with platform_context() as (_session, _user_ctx, repo_factory, broker, secret):
            service = await _build_trigger_service(repo_factory, broker, secret)
            ok = await service.enable_trigger(UUID(trigger_id))
            return json.dumps({"enabled": ok})

    @tool_method(
        display_name="Disable trigger",
        effect="write",
        idempotent=True,
        output=TriggerDisabledOutput,
    )
    @requires("edit", "trigger", id_param="trigger_id")
    async def disable(self, trigger_id: TriggerId) -> str:
        """Disable a trigger (pauses its schedule for cron triggers)."""
        async with platform_context() as (_session, _user_ctx, repo_factory, broker, secret):
            service = await _build_trigger_service(repo_factory, broker, secret)
            ok = await service.disable_trigger(UUID(trigger_id))
            return json.dumps({"disabled": ok})

    @tool_method(
        display_name="Get trigger history",
        effect="read",
        output=builtins.list[TriggerExecutionOutput],
    )
    @unrestricted("execution history, as GET /v1/triggers/{id}/executions serves it")
    async def get_history(
        self,
        trigger_id: TriggerId,
        limit: Annotated[int, Field(description="Most executions to return, newest first.")] = 50,
        offset: Annotated[int, Field(description="Executions to skip before the page starts.")] = 0,
    ) -> str:
        """Get recent execution history for a trigger."""
        async with platform_read_context() as (_session, _user_ctx, repo_factory, broker, secret):
            service = await _build_trigger_service(repo_factory, broker, secret)
            executions = await service.get_execution_history(
                UUID(trigger_id), limit=limit, offset=offset
            )
            return json.dumps(
                [
                    {
                        "id": str(e.id),
                        "status": getattr(e.status, "value", str(e.status)),
                        "executed_at": e.executed_at.isoformat() if e.executed_at else None,
                        "execution_time_ms": e.execution_time_ms,
                        "error_message": e.error_message,
                        "task_id": str(e.task_id) if e.task_id else None,
                    }
                    for e in executions
                ],
                default=str,
            )
