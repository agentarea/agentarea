import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncIterable

from a2a.types import (
    CancelTaskRequest,
    CancelTaskResponse,
    GetTaskPushNotificationConfigRequest,
    GetTaskPushNotificationConfigResponse,
    GetTaskRequest,
    GetTaskResponse,
    JSONRPCResponse,
    SendMessageRequest,
    SendMessageResponse,
    SendStreamingMessageRequest,
    SendStreamingMessageResponse,
    SetTaskPushNotificationConfigRequest,
    SetTaskPushNotificationConfigResponse,
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
    async def on_send_task(self, request: SendMessageRequest) -> SendMessageResponse:
        pass

    @abstractmethod
    async def on_send_task_subscribe(
        self, request: SendStreamingMessageRequest
    ) -> AsyncIterable[SendStreamingMessageResponse] | JSONRPCResponse:
        pass

    @abstractmethod
    async def on_set_task_push_notification(
        self, request: SetTaskPushNotificationConfigRequest
    ) -> SetTaskPushNotificationConfigResponse:
        pass

    @abstractmethod
    async def on_get_task_push_notification(
        self, request: GetTaskPushNotificationConfigRequest
    ) -> GetTaskPushNotificationConfigResponse:
        pass

    @abstractmethod
    async def on_resubscribe_to_task(
        self, request: TaskResubscriptionRequest
    ) -> AsyncIterable[SendMessageResponse] | JSONRPCResponse:
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
