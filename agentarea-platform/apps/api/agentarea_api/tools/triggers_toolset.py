"""TriggersToolset — manage cron and webhook triggers.

Tool method signatures are explicit kwargs (MCP-idiomatic flat wire schema)
but the source of truth for ``create_cron``/``create_webhook`` is the
Pydantic DTO ``TriggerCreate`` in ``agentarea_triggers.schemas.dto``. The
contract test in ``tests/unit/test_mcp_rest_parity.py`` enforces parity
between toolset kwargs and DTO fields.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from agentarea_agents_sdk.tools.decorator_tool import Toolset, tool_method
from agentarea_agents_sdk.tools.tool_definition import toolset
from agentarea_triggers.schemas.dto import TriggerCreate

from .base import platform_context, platform_read_context


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
            namespace=settings.triggers.TEMPORAL_SCHEDULE_NAMESPACE,
            task_queue=settings.triggers.TEMPORAL_SCHEDULE_TASK_QUEUE,
        )
    except Exception:
        temporal_schedule_manager = None

    return TriggerService(
        repository_factory=repo_factory,
        event_broker=event_broker,
        temporal_schedule_manager=temporal_schedule_manager,
        secret_manager=secret_manager,
    )


def _trigger_summary(trigger: Any) -> dict[str, Any]:
    return {
        "id": str(trigger.id),
        "name": trigger.name,
        "description": trigger.description,
        "agent_id": str(trigger.agent_id),
        "trigger_type": getattr(trigger.trigger_type, "value", str(trigger.trigger_type)),
        "is_active": trigger.is_active,
        "cron_expression": getattr(trigger, "cron_expression", None),
        "webhook_id": getattr(trigger, "webhook_id", None),
    }


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
    """Manage triggers: list, get, create cron/webhook, update, delete, enable/disable, history."""

    @tool_method(effect="read")
    async def list(
        self,
        agent_id: str = "",
        active_only: bool = False,
        limit: int = 100,
    ) -> str:
        """List triggers, optionally filtered by agent or active state."""
        async with platform_read_context() as (_session, _user_ctx, repo_factory, broker, secret):
            service = await _build_trigger_service(repo_factory, broker, secret)
            triggers = await service.list_triggers(
                agent_id=UUID(agent_id) if agent_id else None,
                active_only=active_only,
                limit=limit,
            )
            return json.dumps([_trigger_summary(t) for t in triggers], default=str)

    @tool_method(effect="read")
    async def get(self, trigger_id: str) -> str:
        """Get a trigger by ID."""
        async with platform_read_context() as (_session, _user_ctx, repo_factory, broker, secret):
            service = await _build_trigger_service(repo_factory, broker, secret)
            trigger = await service.get_trigger(UUID(trigger_id))
            if not trigger:
                return json.dumps({"error": "Trigger not found"})
            return json.dumps(_trigger_summary(trigger), default=str)

    @tool_method(effect="write")
    async def create_cron(
        self,
        name: str,
        agent_id: str,
        cron_expression: str,
        description: str = "",
        timezone: str = "UTC",
        task_parameters: dict[str, Any] | None = None,
        conditions: dict[str, Any] | None = None,
        enabled: bool = True,
        failure_threshold: int = 5,
    ) -> str:
        """Create a cron-based trigger that fires the given agent on a schedule.

        ``cron_expression`` is a 5- or 6-field expression evaluated in
        ``timezone`` (default UTC). This always repeats — cron cannot express a
        year, so a "one-shot" cron fires again next year. For a single run at a
        given moment use ``runs.start`` with ``scheduled_at`` instead.

        ``task_parameters`` are merged into every task created when the trigger
        fires. ``conditions`` is an optional rule/LLM condition map evaluated
        against event data before firing.
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
            return json.dumps(_trigger_summary(trigger), default=str)

    @tool_method(effect="write")
    async def create_webhook(
        self,
        name: str,
        agent_id: str,
        webhook_id: str = "",
        description: str = "",
        webhook_type: str = "generic",
        allowed_methods: list[str] | None = None,
        task_parameters: dict[str, Any] | None = None,
        conditions: dict[str, Any] | None = None,
        enabled: bool = True,
        failure_threshold: int = 5,
        event_types: list[str] | None = None,
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
            return json.dumps(_trigger_summary(trigger), default=str)

    @tool_method(effect="destructive")
    async def delete(self, trigger_id: str) -> str:
        """Delete a trigger and its schedule."""
        async with platform_context() as (_session, _user_ctx, repo_factory, broker, secret):
            service = await _build_trigger_service(repo_factory, broker, secret)
            deleted = await service.delete_trigger(UUID(trigger_id))
            return json.dumps({"deleted": deleted})

    @tool_method(effect="write")
    async def enable(self, trigger_id: str) -> str:
        """Enable a trigger (resumes its schedule for cron triggers)."""
        async with platform_context() as (_session, _user_ctx, repo_factory, broker, secret):
            service = await _build_trigger_service(repo_factory, broker, secret)
            ok = await service.enable_trigger(UUID(trigger_id))
            return json.dumps({"enabled": ok})

    @tool_method(effect="write")
    async def disable(self, trigger_id: str) -> str:
        """Disable a trigger (pauses its schedule for cron triggers)."""
        async with platform_context() as (_session, _user_ctx, repo_factory, broker, secret):
            service = await _build_trigger_service(repo_factory, broker, secret)
            ok = await service.disable_trigger(UUID(trigger_id))
            return json.dumps({"disabled": ok})

    @tool_method(effect="read")
    async def get_history(self, trigger_id: str, limit: int = 50, offset: int = 0) -> str:
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
