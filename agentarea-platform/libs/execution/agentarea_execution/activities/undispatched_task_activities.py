"""The activity that starts tasks left pending with no workflow."""

from agentarea_common.auth.context import UserContext
from agentarea_common.config import get_database
from agentarea_tasks.task_service import TaskService
from sqlalchemy.ext.asyncio import AsyncSession
from temporalio import activity

from ..interfaces import ActivityDependencies
from ..workflows.undispatched_task_reconciler_workflow import START_UNDISPATCHED_TASKS


def make_undispatched_task_activities(dependencies: ActivityDependencies):
    def _task_service(session: AsyncSession, user_context: UserContext) -> TaskService:
        from agentarea_common.base.repository_factory import RepositoryFactory
        from agentarea_tasks.infrastructure.repository import TaskRepository
        from agentarea_tasks.temporal_task_manager import TemporalTaskManager

        repository_factory = RepositoryFactory(session, user_context)
        return TaskService(
            repository_factory=repository_factory,
            event_broker=dependencies.event_broker,
            task_manager=TemporalTaskManager(
                task_repository=repository_factory.create_repository(TaskRepository),
                temporal_executor=dependencies.workflow_executor,
            ),
        )

    @activity.defn(name=START_UNDISPATCHED_TASKS)
    async def start_undispatched_tasks_activity() -> int:
        from agentarea_tasks.undispatched_tasks import start_undispatched_tasks

        return await start_undispatched_tasks(get_database().async_session_factory, _task_service)

    return [start_undispatched_tasks_activity]
