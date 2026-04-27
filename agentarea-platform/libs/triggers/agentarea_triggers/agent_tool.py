"""Triggers agent toolset — usable from the worker code-tool path.

The platform-side ``agentarea_api.tools.triggers_toolset.TriggersToolset`` lives
in apps/api and is exposed via the native MCP server. The worker doesn't have
``agentarea_api`` on its python path, so a separate Toolset implementation is
needed for in-process agent execution.

This toolset is constructed per task by ``agent_execution_activities`` with
``default_agent_id``/``default_workspace_id``/``default_user_id`` injected via
``extra_kwargs``. The agent therefore doesn't need to know its own id — every
``create_cron`` call defaults to scheduling the calling agent.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from agentarea_agents_sdk.tools.decorator_tool import Toolset, tool_method


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


class TriggersAgentToolset(Toolset):
    """Schedule the calling agent on a cron expression, list/disable/delete its own triggers.

    Construction:
        TriggersAgentToolset(
            default_agent_id=str(agent_id),
            default_workspace_id=str(workspace_id),
            default_user_id=user_id,
            event_broker=<broker>,                  # required for trigger_service
        )

    All methods open a fresh DB session per call (matching the platform
    ``platform_context()`` pattern). The ``temporal_schedule_manager`` is
    instantiated lazily; if Temporal is unavailable the tool still creates the
    DB row and an inactive schedule, which is acceptable for the agent's
    happy-path scheduling intent.
    """

    def __init__(
        self,
        default_agent_id: str | None = None,
        default_workspace_id: str | None = None,
        default_user_id: str | None = None,
        event_broker: Any = None,
    ) -> None:
        super().__init__()
        self._default_agent_id = default_agent_id
        self._default_workspace_id = default_workspace_id
        self._default_user_id = default_user_id
        self._event_broker = event_broker

    def _resolve_agent_id(self, agent_id: str | None) -> str:
        if agent_id and agent_id.strip() and agent_id.strip().upper() != "__SELF__":
            return agent_id.strip()
        if not self._default_agent_id:
            raise ValueError(
                "agent_id is required and no default agent_id is wired into this toolset"
            )
        return self._default_agent_id

    async def _open(self):
        """Open a session + repo factory + trigger service for one call."""
        from agentarea_common.auth.context import UserContext
        from agentarea_common.base.repository_factory import RepositoryFactory
        from agentarea_common.config import get_settings
        from agentarea_common.config import get_database

        from .temporal_schedule_manager import TemporalScheduleManager
        from .trigger_service import TriggerService

        if not self._default_workspace_id or not self._default_user_id:
            raise RuntimeError(
                "TriggersAgentToolset is missing workspace_id/user_id context"
            )

        database = get_database()
        if database is None:
            raise RuntimeError("database not initialised in worker context")

        session = database.async_session_factory()
        try:
            user_context = UserContext(
                user_id=self._default_user_id,
                workspace_id=self._default_workspace_id,
            )
            repo_factory = RepositoryFactory(session, user_context)

            settings = get_settings()
            schedule_mgr: TemporalScheduleManager | None = None
            try:
                schedule_mgr = TemporalScheduleManager(
                    namespace=settings.triggers.TEMPORAL_SCHEDULE_NAMESPACE,
                    task_queue=settings.triggers.TEMPORAL_SCHEDULE_TASK_QUEUE,
                )
            except Exception:
                schedule_mgr = None

            service = TriggerService(
                repository_factory=repo_factory,
                event_broker=self._event_broker,
                temporal_schedule_manager=schedule_mgr,
            )
            return session, user_context, service
        except Exception:
            await session.close()
            raise

    @tool_method
    async def create_cron(
        self,
        name: str,
        cron_expression: str,
        description: str = "",
        timezone: str = "UTC",
        agent_id: str = "",
    ) -> str:
        """Create a cron-based trigger that fires the given (or calling) agent on a schedule.

        ``cron_expression`` is a 5-field expression in the given ``timezone``
        (default UTC). For one-shot reminders set day-of-month + month so the
        cron only matches the intended date.

        ``agent_id`` defaults to the calling agent — pass it explicitly only to
        schedule a different agent in the same workspace.
        """
        session, _user_ctx, service = await self._open()
        try:
            from .domain.enums import TriggerType
            from .domain.models import TriggerCreate

            target_agent_id = self._resolve_agent_id(agent_id or None)
            data = TriggerCreate(
                name=name,
                description=description,
                agent_id=UUID(target_agent_id),
                trigger_type=TriggerType.CRON,
                cron_expression=cron_expression,
                timezone=timezone,
                created_by=self._default_user_id or "agent",
                workspace_id=self._default_workspace_id or "",
            )
            trigger = await service.create_trigger(data)
            await session.commit()
            return json.dumps(_trigger_summary(trigger), default=str)
        except Exception as exc:
            await session.rollback()
            return json.dumps({"error": f"create_cron failed: {exc}"})
        finally:
            await session.close()

    @tool_method
    async def list(self, active_only: bool = False, limit: int = 50) -> str:
        """List triggers in the workspace (optionally only active ones)."""
        session, _user_ctx, service = await self._open()
        try:
            triggers = await service.list_triggers(active_only=active_only, limit=limit)
            return json.dumps(
                [_trigger_summary(t) for t in triggers], default=str
            )
        finally:
            await session.close()

    @tool_method
    async def disable(self, trigger_id: str) -> str:
        """Pause a trigger's schedule."""
        session, _user_ctx, service = await self._open()
        try:
            ok = await service.disable_trigger(UUID(trigger_id))
            await session.commit()
            return json.dumps({"disabled": ok})
        except Exception as exc:
            await session.rollback()
            return json.dumps({"error": f"disable failed: {exc}"})
        finally:
            await session.close()

    @tool_method
    async def delete(self, trigger_id: str) -> str:
        """Delete a trigger and its schedule."""
        session, _user_ctx, service = await self._open()
        try:
            ok = await service.delete_trigger(UUID(trigger_id))
            await session.commit()
            return json.dumps({"deleted": ok})
        except Exception as exc:
            await session.rollback()
            return json.dumps({"error": f"delete failed: {exc}"})
        finally:
            await session.close()
