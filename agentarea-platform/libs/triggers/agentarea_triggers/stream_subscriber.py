"""A trigger as a stream subscriber: check the configurer, fire, report the outcome."""

import logging
from collections.abc import Callable
from uuid import UUID

from agentarea_common.auth.context import UserContext
from agentarea_common.auth.permission import PermissionService
from agentarea_common.base.repository_factory import RepositoryFactory
from agentarea_common.events.broker import EventBroker
from agentarea_common.rebac import OpenFGAClient
from agentarea_common.workflow.executor import WorkflowExecutor
from agentarea_common.workspaces.memberships import (
    check_workspace_membership,
    is_workspace_owner,
)
from agentarea_secrets.secret_manager_factory import SecretManagerFactory
from agentarea_streams.domain import HandlerResult, JournaledEvent, SubscriptionView, Verdict
from agentarea_streams.domain.keys import task_id_for
from sqlalchemy.ext.asyncio import AsyncSession

from .llm_condition_evaluator import build_condition_evaluator
from .trigger_service import TriggerService

logger = logging.getLogger(__name__)

_VERDICTS = {"reacted": Verdict.REACTED, "skipped": Verdict.SKIPPED, "error": Verdict.ERROR}


class ConfigurerAuthority:
    """Whether whoever configured a trigger may still run its agent."""

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
        return await self._permissions.check(user_id, "execute", "agent", str(agent_id))


class TriggerSubscriptionHandler:
    def __init__(
        self,
        *,
        event_broker: EventBroker,
        secret_manager_factory: SecretManagerFactory,
        workflow_executor: WorkflowExecutor,
        authority: ConfigurerAuthority,
        trigger_service_factory: Callable[[AsyncSession, UserContext], TriggerService]
        | None = None,
    ):
        self._event_broker = event_broker
        self._secret_manager_factory = secret_manager_factory
        self._workflow_executor = workflow_executor
        self._authority = authority
        self._trigger_service_factory = trigger_service_factory or self._build_trigger_service

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

    async def handle(
        self, subscription: SubscriptionView, event: JournaledEvent, session: AsyncSession
    ) -> HandlerResult:
        from agentarea_tasks.domain.models import TaskProvenance

        if subscription.trigger_id is None:
            raise ValueError(f"trigger subscription {subscription.id} names no trigger")
        context = UserContext(
            user_id=subscription.created_by, workspace_id=subscription.workspace_id
        )
        service = self._trigger_service_factory(session, context)
        trigger = await service.get_trigger(subscription.trigger_id)
        if trigger is None:
            return HandlerResult(verdict=Verdict.ERROR, reason="trigger no longer exists")
        if not trigger.is_active:
            return HandlerResult(verdict=Verdict.SKIPPED, reason="trigger is inactive")
        if not await self._authority.may_run(
            session,
            user_id=trigger.created_by,
            workspace_id=subscription.workspace_id,
            agent_id=trigger.agent_id,
        ):
            await service.trigger_repository.mark_needs_new_owner(trigger.id)
            logger.warning(
                "Trigger %s stopped: %s can no longer run agent %s",
                trigger.id,
                trigger.created_by,
                trigger.agent_id,
            )
            return HandlerResult(
                verdict=Verdict.ERROR,
                reason=(
                    f"configurer_lost_access: {trigger.created_by} can no longer run agent "
                    f"{trigger.agent_id}; the trigger needs a new owner"
                ),
            )
        firing = await service.fire(
            trigger.id,
            event.data,
            task_id=task_id_for(subscription.id, event.sequence),
            provenance=TaskProvenance(
                origin_type="trigger",
                origin_id=str(trigger.id),
                correlation_id=event.correlation_id or str(event.id),
                causation_id=str(event.id),
            ),
        )
        return HandlerResult(
            verdict=_VERDICTS[firing.outcome],
            reason=firing.reason,
            score=firing.verdict.score if firing.verdict else None,
            task_id=firing.task_id,
        )
