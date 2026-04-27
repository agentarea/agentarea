"""TriggersToolset — manage cron and webhook triggers."""

import json
from typing import Any
from uuid import UUID

from agentarea_agents_sdk.tools.decorator_tool import Toolset, tool_method

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


class TriggersToolset(Toolset):
    """Manage triggers: list, get, create cron/webhook, update, delete, enable/disable, history."""

    @tool_method
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

    @tool_method
    async def get(self, trigger_id: str) -> str:
        """Get a trigger by ID."""
        async with platform_read_context() as (_session, _user_ctx, repo_factory, broker, secret):
            service = await _build_trigger_service(repo_factory, broker, secret)
            trigger = await service.get_trigger(UUID(trigger_id))
            if not trigger:
                return json.dumps({"error": "Trigger not found"})
            return json.dumps(_trigger_summary(trigger), default=str)

    @tool_method
    async def create_cron(
        self,
        name: str,
        agent_id: str,
        cron_expression: str,
        description: str = "",
        timezone: str = "UTC",
    ) -> str:
        """Create a cron-based trigger that fires the given agent on a schedule."""
        async with platform_context() as (_session, user_ctx, repo_factory, broker, secret):
            from agentarea_triggers.domain.enums import TriggerType
            from agentarea_triggers.domain.models import TriggerCreate

            service = await _build_trigger_service(repo_factory, broker, secret)
            data = TriggerCreate(
                name=name,
                description=description,
                agent_id=UUID(agent_id),
                trigger_type=TriggerType.CRON,
                cron_expression=cron_expression,
                timezone=timezone,
                created_by=user_ctx.user_id,
                workspace_id=user_ctx.workspace_id,
            )
            trigger = await service.create_trigger(data)
            return json.dumps(_trigger_summary(trigger), default=str)

    @tool_method
    async def create_webhook(
        self,
        name: str,
        agent_id: str,
        webhook_id: str,
        description: str = "",
        webhook_type: str = "generic",
    ) -> str:
        """Create a webhook trigger. Inbound webhook URL becomes /webhooks/{webhook_id}."""
        async with platform_context() as (_session, user_ctx, repo_factory, broker, secret):
            from agentarea_triggers.domain.enums import TriggerType
            from agentarea_triggers.domain.models import TriggerCreate

            service = await _build_trigger_service(repo_factory, broker, secret)
            data = TriggerCreate(
                name=name,
                description=description,
                agent_id=UUID(agent_id),
                trigger_type=TriggerType.WEBHOOK,
                webhook_id=webhook_id,
                webhook_type=webhook_type,
                created_by=user_ctx.user_id,
                workspace_id=user_ctx.workspace_id,
            )
            trigger = await service.create_trigger(data)
            return json.dumps(_trigger_summary(trigger), default=str)

    @tool_method
    async def delete(self, trigger_id: str) -> str:
        """Delete a trigger and its schedule."""
        async with platform_context() as (_session, _user_ctx, repo_factory, broker, secret):
            service = await _build_trigger_service(repo_factory, broker, secret)
            deleted = await service.delete_trigger(UUID(trigger_id))
            return json.dumps({"deleted": deleted})

    @tool_method
    async def enable(self, trigger_id: str) -> str:
        """Enable a trigger (resumes its schedule for cron triggers)."""
        async with platform_context() as (_session, _user_ctx, repo_factory, broker, secret):
            service = await _build_trigger_service(repo_factory, broker, secret)
            ok = await service.enable_trigger(UUID(trigger_id))
            return json.dumps({"enabled": ok})

    @tool_method
    async def disable(self, trigger_id: str) -> str:
        """Disable a trigger (pauses its schedule for cron triggers)."""
        async with platform_context() as (_session, _user_ctx, repo_factory, broker, secret):
            service = await _build_trigger_service(repo_factory, broker, secret)
            ok = await service.disable_trigger(UUID(trigger_id))
            return json.dumps({"disabled": ok})

    @tool_method
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
