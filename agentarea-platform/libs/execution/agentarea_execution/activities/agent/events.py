"""Storing a run's workflow events and putting them on the broker."""

import json
import logging
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from agentarea_common.auth.context import UserContext
from agentarea_common.events.contract import LIVE_ONLY_TYPES
from agentarea_common.events.task_stream import broadcast_live, publish_task_event, task_event
from agentarea_common.extensions.customer_pricing import get_customer_pricing
from agentarea_tasks.domain.costs import CostEntry
from agentarea_tasks.infrastructure.cost_repository import CostEntryRepository
from temporalio import activity

from ...interfaces import ActivityDependencies
from ...models import WorkflowEventsRequest, WorkflowEventsResult
from .cost_ledger import cost_entries
from .tool_audit import record_tool_audit, tool_audit_entry

if TYPE_CHECKING:
    from ..dependencies import ActivityServiceContainer

logger = logging.getLogger(__name__)


def ledger_lines(
    events: list[dict[str, Any]], *, workspace_id: str, user_id: str
) -> list[CostEntry]:
    """The spend ledger lines a batch of workflow events stands for."""
    billing_currency = get_customer_pricing().currency()
    return [
        entry
        for event in events
        for entry in cost_entries(
            event,
            workspace_id=workspace_id,
            created_by=user_id,
            billing_currency=billing_currency,
        )
    ]


async def store_task_events(
    ctx: Any, events: list[dict[str, Any]], *, workspace_id: str, user_id: str
) -> list[Any]:
    """Store each event in ``task_events`` once under the workflow's id; the stored rows."""
    task_event_service = await ctx.get_task_event_service()
    return [
        await task_event_service.create_workflow_event(
            task_id=UUID(event["data"]["task_id"]),
            event_id=UUID(event["event_id"]),
            event_type=event["event_type"],
            data=event["data"],
            timestamp=datetime.fromisoformat(event["timestamp"]),
            workspace_id=workspace_id,
            created_by=user_id,
        )
        for event in events
    ]


async def publish_events(
    dependencies: ActivityDependencies, events: list[dict[str, Any]], *, workspace_id: str
) -> None:
    """Publish stored workflow events to ``tasks.events``; broadcast the live-only ones."""
    broker = dependencies.broker_client
    if broker is None:
        raise RuntimeError("publishing task events needs a broker client")
    for event in events:
        envelope = task_event(
            task_id=str(event["data"]["task_id"]),
            workspace_id=workspace_id,
            event_type=event["event_type"],
            event_id=event["event_id"],
            timestamp=datetime.fromisoformat(event["timestamp"]),
            data=event["data"],
        )
        if envelope.type in LIVE_ONLY_TYPES:
            await broadcast_live(broker, envelope)
        else:
            await publish_task_event(broker, envelope)


def make_events_activities(
    dependencies: ActivityDependencies, container: ActivityServiceContainer
) -> list[Callable[..., Any]]:
    from ..dependencies import ActivityContext

    @activity.defn
    async def publish_workflow_events_activity(
        request: WorkflowEventsRequest,
    ) -> WorkflowEventsResult:
        """Store each event of a run from before the task log, then publish it.

        Kept registered for those runs' histories; a run on the task log records
        through the record activity. The ``task_events`` row is committed first,
        together with the audit rows of the tool-call outcomes and the spend
        ledger lines of the paid calls the batch holds, then each event goes to
        ``tasks.events`` (a live-only one is broadcast). Any failure raises so
        Temporal retries the whole batch; every step is keyed by the workflow's
        ``event_id``, so a repeat writes nothing twice and readers dedup by it.
        """
        user_context = UserContext(user_id=request.user_id, workspace_id=request.workspace_id)

        try:
            events = [json.loads(event_json) for event_json in request.events_json]
            async with ActivityContext(container, user_context) as ctx:
                await store_task_events(
                    ctx, events, workspace_id=request.workspace_id, user_id=request.user_id
                )
                audited = [
                    (UUID(event["event_id"]), entry)
                    for event in events
                    if (entry := tool_audit_entry(event)) is not None
                ]
                if audited:
                    audit = await ctx.get_audit_service()
                    for event_id, entry in audited:
                        await record_tool_audit(
                            audit, event_id, entry, requested_by=request.user_id
                        )
                costs = ledger_lines(
                    events, workspace_id=request.workspace_id, user_id=request.user_id
                )
                if costs:
                    session = container._database.async_session_factory()
                    ctx._sessions.append(session)
                    await CostEntryRepository(session, user_context).record(costs)

            await publish_events(dependencies, events, workspace_id=request.workspace_id)
        except Exception:
            logger.error(
                "Failed to publish %d workflow events for workspace %s",
                len(request.events_json),
                request.workspace_id,
                exc_info=True,
            )
            raise

        return WorkflowEventsResult(success=True, events_published=len(request.events_json))

    return [
        publish_workflow_events_activity,
    ]
