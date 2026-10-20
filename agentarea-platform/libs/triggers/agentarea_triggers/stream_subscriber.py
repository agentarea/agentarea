"""A trigger as a stream subscriber: check the configurer, fire, report the outcome."""

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from agentarea_common.auth.context import Subject, UserContext
from agentarea_common.auth.permission import PermissionService
from agentarea_common.base.repository_factory import RepositoryFactory
from agentarea_common.events.broker import EventBroker
from agentarea_common.rebac import OpenFGAClient
from agentarea_common.workflow.executor import WorkflowExecutor
from agentarea_common.workspaces.memberships import (
    check_workspace_membership,
    is_workspace_owner,
)
from agentarea_execution.workflows.trigger_batch_workflow import BatchSpec
from agentarea_secrets.secret_manager_factory import SecretManagerFactory
from agentarea_streams.domain import HandlerResult, StreamEvent, SubscriptionView, Verdict
from agentarea_streams.domain.keys import task_id_for
from sqlalchemy.ext.asyncio import AsyncSession

from .batches import TriggerBatches, batch_workflow_id
from .channels.sender_admission import Refused, TelegramSenderAdmission, event_admission
from .delivery_address import event_body, firing_delivery
from .domain.models import StreamTrigger, TriggerBatchWindow
from .event_context import TriggerEvent
from .failures import is_permanent
from .infrastructure.causation_repository import StoredCausationChain
from .infrastructure.reactions import CausedExecutionRepository, ReactionRepository, StreamCause
from .llm_condition_evaluator import build_condition_evaluator
from .loop_guard import CausationChainFactory, own_task_in_chain
from .trigger_service import TriggerService

logger = logging.getLogger(__name__)

_VERDICTS = {"reacted": Verdict.REACTED, "skipped": Verdict.SKIPPED, "error": Verdict.ERROR}


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class SubscriptionFollowUpClaim:
    """The reaction row of one (subscription, event), written before a routed follow-up.

    A follow-up routed into a running workflow stores no task, so the
    deterministic task id cannot recognise it on redelivery. The reaction is
    unique per (subscription, event) and is what the router records afterwards
    anyway, so committing it before the signal is the durable mark that the
    message went out. A crash between that commit and the signal loses the
    follow-up rather than doubling it.
    """

    def __init__(self, session: AsyncSession, subscription: SubscriptionView, event: StreamEvent):
        self._session = session
        self._cause = StreamCause.of(subscription, event)
        self._reactions = ReactionRepository(
            session,
            UserContext(user_id=subscription.created_by, workspace_id=subscription.workspace_id),
        )

    async def delivered_to(self) -> UUID | None:
        """The task an earlier attempt routed this event's follow-up into, if any."""
        return await self._reactions.reacted_task(self._cause.subscription_id, self._cause.event_id)

    async def claim(self, task_id: UUID) -> bool:
        _, inserted = await self._reactions.insert_once(
            self._cause,
            {
                "status": "success",
                "verdict": Verdict.REACTED.value,
                "reason": f"follow-up queued into running task {task_id}",
                "task_id": task_id,
            },
            now=_utcnow(),
        )
        await self._session.commit()
        return inserted

    async def release(self) -> None:
        await self._reactions.delete_for_event(self._cause.subscription_id, self._cause.event_id)
        await self._session.commit()


class InvokerAuthority:
    """Whether a person may make an agent act: a member who holds ``can_invoke`` on it.

    Asked of whoever starts a run, never of whoever configured a trigger: a
    trigger's run acts as its agent, so its configurer leaving stops nothing.
    """

    def __init__(self, *, graph: OpenFGAClient, permissions: PermissionService):
        self._graph = graph
        self._permissions = permissions

    async def may_run(
        self, session: AsyncSession, *, user_id: str, workspace_id: str, agent_id: UUID
    ) -> bool:
        if not await is_workspace_owner(session, user_id, workspace_id) and not (
            await check_workspace_membership(
                self._graph, workspace_id=workspace_id, user_id=user_id
            )
        ):
            return False
        return await self._permissions.check(
            Subject(kind="user", id=user_id).graph_subject, "execute", "agent", str(agent_id)
        )


class TriggerSubscriptionHandler:
    def __init__(
        self,
        *,
        event_broker: EventBroker,
        secret_manager_factory: SecretManagerFactory,
        workflow_executor: WorkflowExecutor,
        max_depth: int,
        trigger_service_factory: Callable[[AsyncSession, UserContext], TriggerService]
        | None = None,
        follow_up_claim_factory: Callable[
            [AsyncSession, SubscriptionView, StreamEvent], SubscriptionFollowUpClaim
        ] = SubscriptionFollowUpClaim,
        sender_admission: TelegramSenderAdmission | None = None,
        causation_chain: CausationChainFactory = StoredCausationChain,
        batches: TriggerBatches,
        batch_cap: int,
    ):
        self._event_broker = event_broker
        self._secret_manager_factory = secret_manager_factory
        self._workflow_executor = workflow_executor
        self._trigger_service_factory = trigger_service_factory or self._build_trigger_service
        self._follow_up_claim_factory = follow_up_claim_factory
        self._sender_admission = sender_admission
        self._max_depth = max_depth
        self._causation_chain = causation_chain
        self._batches = batches
        self._batch_cap = batch_cap

    def trigger_service(self, session: AsyncSession, context: UserContext) -> TriggerService:
        return self._trigger_service_factory(session, context)

    def _build_trigger_service(self, session: AsyncSession, context: UserContext) -> TriggerService:
        from agentarea_tasks.infrastructure.repository import TaskRepository
        from agentarea_tasks.task_service import TaskService
        from agentarea_tasks.temporal_task_manager import TemporalTaskManager

        repository_factory = RepositoryFactory(session, context)
        task_service = TaskService(
            repository_factory=repository_factory,
            event_broker=self._event_broker,
            task_manager=TemporalTaskManager(
                task_repository=repository_factory.create_repository(TaskRepository),
                temporal_executor=self._workflow_executor,
            ),
        )
        return TriggerService(
            repository_factory=repository_factory,
            event_broker=self._event_broker,
            task_service=task_service,
            llm_condition_evaluator=build_condition_evaluator(
                session=session,
                user_context=context,
                secret_manager=self._secret_manager_factory.create(
                    session=session, user_context=context
                ),
                secret_manager_factory=self._secret_manager_factory,
                event_broker=self._event_broker,
            ),
        )

    def _service(
        self, session: AsyncSession, context: UserContext, cause: StreamCause
    ) -> TriggerService:
        """A trigger service whose every execution row is this subscription's reaction."""
        service = self._trigger_service_factory(session, context)
        service.trigger_execution_repository = CausedExecutionRepository(session, context, cause)
        return service

    async def handle(
        self, subscription: SubscriptionView, event: StreamEvent, session: AsyncSession
    ) -> HandlerResult:
        from agentarea_tasks.domain.models import TaskProvenance

        if subscription.trigger_id is None:
            raise ValueError(f"trigger subscription {subscription.id} names no trigger")
        context = UserContext(
            user_id=subscription.created_by, workspace_id=subscription.workspace_id
        )
        cause = StreamCause.of(subscription, event)
        service = self._service(session, context, cause)
        trigger = await service.get_trigger(subscription.trigger_id)
        if trigger is None:
            return HandlerResult(verdict=Verdict.ERROR, reason="trigger no longer exists")
        follow_up_claim = self._follow_up_claim_factory(session, subscription, event)
        routed_to = await follow_up_claim.delivered_to()
        if routed_to is not None:
            return HandlerResult(
                verdict=Verdict.REACTED,
                reason=f"follow-up already queued into running task {routed_to}",
                task_id=routed_to,
            )
        if not trigger.is_active:
            return HandlerResult(verdict=Verdict.SKIPPED, reason="trigger is inactive")
        depth = event.depth + 1
        if depth > self._max_depth:
            return HandlerResult(
                verdict=Verdict.SKIPPED,
                reason=f"causation depth {depth} exceeds {self._max_depth}",
            )
        own = await own_task_in_chain(
            self._causation_chain(session, subscription.workspace_id),
            trigger_id=trigger.id,
            event=event,
            max_hops=self._max_depth,
        )
        if own is not None:
            return HandlerResult(
                verdict=Verdict.SKIPPED,
                reason=f"the event comes from task {own}, which this trigger started",
            )
        # A messenger is a door to the agent, not a grant: whoever wrote must be a
        # linked user the graph lets run it, and the run is theirs. Without the
        # admission wired, nobody gets through.
        caller: str | None = None
        try:
            door = await event_admission(session, event)
        except LookupError as error:
            logger.exception("Event %s cannot be admitted: %s", event.id, error)
            return HandlerResult(verdict=Verdict.ERROR, reason=f"sender admission: {error}")
        if door is not None:
            if self._sender_admission is None:
                return HandlerResult(
                    verdict=Verdict.ERROR, reason="no sender admission is wired for this source"
                )
            admission = await self._sender_admission.admit(session, trigger, event, door)
            if isinstance(admission, Refused):
                return HandlerResult(verdict=Verdict.SKIPPED, reason=admission.reason)
            caller = admission.user_id
        # The run acts as the agent, so the agent is what must still stand; who
        # configured the trigger lends it nothing and leaving stops nothing.
        if not await service.agent_stands(trigger.agent_id):
            if not await service.trigger_repository.mark_needs_new_owner(trigger.id):
                raise RuntimeError(
                    f"trigger {trigger.id} could not be stopped for attention: no row updated"
                )
            logger.warning(
                "Trigger %s stopped: agent %s is gone or inactive", trigger.id, trigger.agent_id
            )
            return HandlerResult(
                verdict=Verdict.ERROR,
                reason=(
                    f"agent_unavailable: agent {trigger.agent_id} is gone or inactive; "
                    "the trigger needs attention"
                ),
            )
        stream = await service.stream_service.get_stream(event.stream_id)
        trigger_event = TriggerEvent.from_stream_event(
            event, stream_name=stream.name, body=await event_body(event.data, event.workspace_id)
        )
        if isinstance(trigger, StreamTrigger) and trigger.batch is not None:
            return await self._join_batch(
                service, trigger, trigger.batch, subscription, event, trigger_event, caller
            )
        if caller is not None:
            service = self._service(
                session, UserContext(user_id=caller, workspace_id=subscription.workspace_id), cause
            )
        firing = await service.fire(
            trigger.id,
            trigger_event.data,
            event=trigger_event,
            task_id=task_id_for(subscription.id, event.id),
            provenance=TaskProvenance(
                origin_type="trigger",
                origin_id=str(trigger.id),
                correlation_id=cause.correlation_id,
                causation_id=cause.causation_id,
                depth=event.depth,
            ),
            follow_up_claim=follow_up_claim,
            raise_retryable=True,
            caller=caller,
            delivery=await firing_delivery(
                session,
                event,
                trigger_id=trigger.id,
                session_setting=trigger.session if isinstance(trigger, StreamTrigger) else None,
                body=trigger_event.data.get("body"),
            ),
        )
        return HandlerResult(
            verdict=_VERDICTS[firing.outcome],
            reason=firing.reason,
            score=firing.verdict.score if firing.verdict else None,
            task_id=firing.task_id,
        )

    async def _join_batch(
        self,
        service: TriggerService,
        trigger: StreamTrigger,
        window: TriggerBatchWindow,
        subscription: SubscriptionView,
        event: StreamEvent,
        trigger_event: TriggerEvent,
        caller: str | None,
    ) -> HandlerResult:
        """Hand an admitted event that meets the conditions to the trigger's open batch."""
        if trigger.conditions:
            try:
                verdict = await service.evaluate_trigger_verdict(trigger, trigger_event.data)
            except Exception as error:
                if not is_permanent(error):
                    raise
                logger.warning(
                    "Trigger %s could not decide event %s: %s",
                    trigger.id,
                    event.id,
                    error,
                    exc_info=True,
                )
                return HandlerResult(verdict=Verdict.ERROR, reason=str(error))
            if not verdict.met:
                return HandlerResult(
                    verdict=Verdict.SKIPPED, reason=verdict.reason, score=verdict.score
                )
        workflow_id = batch_workflow_id(trigger.id, caller)
        await self._batches.add(
            BatchSpec(
                trigger_id=trigger.id,
                subscription_id=subscription.id,
                workspace_id=subscription.workspace_id,
                configured_by=subscription.created_by,
                caller=caller,
                window_seconds=window.window_seconds(),
                max_events=min(window.max_events or self._batch_cap, self._batch_cap),
            ),
            event.id,
            workflow_id=workflow_id,
        )
        return HandlerResult(
            verdict=Verdict.BATCHED,
            reason=f"held in batch {workflow_id}",
            workflow_id=workflow_id,
        )
