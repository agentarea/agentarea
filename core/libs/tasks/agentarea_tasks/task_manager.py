import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncIterable

# from agentarea_common.utils import new_not_implemented_error
from agentarea_common.utils.types import (
    CancelTaskRequest,
    CancelTaskResponse,
    GetTaskPushNotificationRequest,
    GetTaskPushNotificationResponse,
    GetTaskRequest,
    GetTaskResponse,
    JSONRPCResponse,
    SendTaskRequest,
    SendTaskResponse,
    SendTaskStreamingRequest,
    SendTaskStreamingResponse,
    SetTaskPushNotificationRequest,
    SetTaskPushNotificationResponse,
    Task,
    TaskResubscriptionRequest,
)

logger = logging.getLogger(__name__)


class BaseTaskManager(ABC):
    @abstractmethod
    async def on_get_task(self, request: GetTaskRequest) -> GetTaskResponse:
        pass

    @abstractmethod
    async def on_cancel_task(self, request: CancelTaskRequest) -> CancelTaskResponse:
        pass

    @abstractmethod
    async def on_send_task(self, request: SendTaskRequest) -> SendTaskResponse:
        pass

    @abstractmethod
    async def on_send_task_subscribe(
        self, request: SendTaskStreamingRequest
    ) -> AsyncIterable[SendTaskStreamingResponse] | JSONRPCResponse:
        pass

    @abstractmethod
    async def on_set_task_push_notification(
        self, request: SetTaskPushNotificationRequest
    ) -> SetTaskPushNotificationResponse:
        pass

    @abstractmethod
    async def on_get_task_push_notification(
        self, request: GetTaskPushNotificationRequest
    ) -> GetTaskPushNotificationResponse:
        pass

    @abstractmethod
    async def on_resubscribe_to_task(
        self, request: TaskResubscriptionRequest
    ) -> AsyncIterable[SendTaskResponse] | JSONRPCResponse:
        pass

    # ------------------------------------------------------------------ #
    # Extended querying capabilities                                     #
    # ------------------------------------------------------------------ #

    @abstractmethod
    async def on_get_tasks_by_user(self, user_id: str) -> list[Task]:
        """Retrieve all tasks that were created by / assigned to a specific user.

        Parameters
        ----------
        user_id: str
            Identifier of the user whose tasks are requested.
        """
        pass

    @abstractmethod
    async def on_get_tasks_by_agent(self, agent_id: str) -> list[Task]:
        """Retrieve all tasks that are currently assigned to a specific agent.

        Parameters
        ----------
        agent_id: str
            Identifier of the agent whose tasks are requested.
        """
        pass
