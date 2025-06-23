import asyncio
import logging
from abc import abstractmethod
from collections.abc import AsyncIterable

from agentarea.common.utils.types import (
    Artifact,
    CancelTaskRequest,
    CancelTaskResponse,
    GetTaskPushNotificationRequest,
    GetTaskPushNotificationResponse,
    GetTaskRequest,
    GetTaskResponse,
    InternalError,
    JSONRPCError,
    JSONRPCResponse,
    PushNotificationConfig,
    SendTaskRequest,
    SendTaskResponse,
    SendTaskStreamingRequest,
    SendTaskStreamingResponse,
    SetTaskPushNotificationRequest,
    SetTaskPushNotificationResponse,
    Task,
    TaskIdParams,
    TaskNotCancelableError,
    TaskNotFoundError,
    TaskPushNotificationConfig,
    TaskQueryParams,
    TaskResubscriptionRequest,
    TaskSendParams,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
    TextPart,
)
from agentarea.modules.tasks.task_manager import BaseTaskManager

new_not_implemented_error = JSONRPCResponse(
    id=None,
    error=JSONRPCError(
        code=-32004,  # UnsupportedOperationError code
        message="Not implemented",
    ),
)


logger = logging.getLogger(__name__)


class InMemoryTaskManager(BaseTaskManager):
    def __init__(self):
        self.tasks: dict[str, Task] = {}
        self.push_notification_infos: dict[str, PushNotificationConfig] = {}
        self.lock = asyncio.Lock()
        self.task_sse_subscribers: dict[str, list[asyncio.Queue[SendTaskStreamingResponse]]] = {}
        self.subscriber_lock = asyncio.Lock()

    async def on_get_task(self, request: GetTaskRequest) -> GetTaskResponse:
        logger.info(f"Getting task {request.params.id}")
        task_query_params: TaskQueryParams = request.params

        async with self.lock:
            task = self.tasks.get(task_query_params.id)
            if task is None:
                return GetTaskResponse(id=request.id, error=TaskNotFoundError())

            task_result = self.append_task_history(task, task_query_params.historyLength)

        return GetTaskResponse(id=request.id, result=task_result)

    async def on_cancel_task(self, request: CancelTaskRequest) -> CancelTaskResponse:
        logger.info(f"Cancelling task {request.params.id}")
        task_id_params: TaskIdParams = request.params

        async with self.lock:
            task = self.tasks.get(task_id_params.id)
            if task is None:
                return CancelTaskResponse(id=request.id, error=TaskNotFoundError())

        return CancelTaskResponse(id=request.id, error=TaskNotCancelableError())

    async def on_send_task(self, request: SendTaskRequest) -> SendTaskResponse:
        """Handle A2A task sending."""
        logger.info(f"Sending task {request.params.id}")
        
        try:
            # Create or update the task
            task = await self.upsert_task(request.params)
            
            # Simulate task processing by updating status to working
            task.status.state = TaskState.WORKING
            
            # For demo purposes, immediately complete simple text tasks
            if task.history and len(task.history) > 0:
                latest_message = task.history[-1]
                if latest_message.parts and latest_message.parts[0].type == 'text':
                    # Create a simple response artifact
                    response_text = f"Processed: {latest_message.parts[0].text}"
                    response_artifact = Artifact(
                        name="response",
                        parts=[TextPart(text=response_text)],
                        metadata={"type": "response", "timestamp": str(task.status.timestamp)}
                    )
                    
                    # Update task with completion
                    task.status.state = TaskState.COMPLETED
                    if task.artifacts is None:
                        task.artifacts = []
                    task.artifacts.append(response_artifact)
            
            return SendTaskResponse(id=request.id, result=task)
            
        except Exception as e:
            logger.error(f"Error in on_send_task: {e}", exc_info=True)
            return SendTaskResponse(
                id=request.id,
                error=InternalError(message=f"Failed to send task: {str(e)}")
            )

    async def on_send_task_subscribe(
        self, request: SendTaskStreamingRequest
    ) -> AsyncIterable[SendTaskStreamingResponse] | JSONRPCResponse:
        """Handle A2A task streaming subscription."""
        logger.info(f"Starting task streaming for {request.params.id}")
        
        try:
            # First, send the task if it doesn't exist
            task = self.tasks.get(request.params.id)
            if task is None:
                send_response = await self.on_send_task(
                    SendTaskRequest(id=request.id, params=request.params)
                )
                if send_response.error:
                    return JSONRPCResponse(id=request.id, error=send_response.error)
                task = send_response.result
            
            # Set up SSE streaming
            await self.setup_sse_consumer(request.params.id)
            
            # Return streaming generator
            return self.dequeue_events_for_sse(request.id, request.params.id, 
                                               self.task_sse_subscribers.get(request.params.id, [None])[0])
                
        except Exception as e:
            logger.error(f"Error in on_send_task_subscribe: {e}", exc_info=True)
            return JSONRPCResponse(
                id=request.id,
                error=InternalError(message=f"Failed to subscribe to task: {str(e)}")
            )

    async def set_push_notification_info(
        self, task_id: str, notification_config: PushNotificationConfig
    ):
        async with self.lock:
            task = self.tasks.get(task_id)
            if task is None:
                raise ValueError(f"Task not found for {task_id}")

            self.push_notification_infos[task_id] = notification_config

    async def get_push_notification_info(self, task_id: str) -> PushNotificationConfig:
        async with self.lock:
            task = self.tasks.get(task_id)
            if task is None:
                raise ValueError(f"Task not found for {task_id}")

            return self.push_notification_infos[task_id]

        return None

    async def has_push_notification_info(self, task_id: str) -> bool:
        async with self.lock:
            return task_id in self.push_notification_infos

    async def on_set_task_push_notification(
        self, request: SetTaskPushNotificationRequest
    ) -> SetTaskPushNotificationResponse:
        logger.info(f"Setting task push notification {request.params.id}")
        task_notification_params: TaskPushNotificationConfig = request.params

        try:
            await self.set_push_notification_info(
                task_notification_params.id,
                task_notification_params.pushNotificationConfig,
            )
        except Exception as e:
            logger.error(f"Error while setting push notification info: {e}")
            return JSONRPCResponse(
                id=request.id,
                error=InternalError(
                    message="An error occurred while setting push notification info"
                ),
            )

        return SetTaskPushNotificationResponse(id=request.id, result=task_notification_params)

    async def on_get_task_push_notification(
        self, request: GetTaskPushNotificationRequest
    ) -> GetTaskPushNotificationResponse:
        logger.info(f"Getting task push notification {request.params.id}")
        task_params: TaskIdParams = request.params

        try:
            notification_info = await self.get_push_notification_info(task_params.id)
        except Exception as e:
            logger.error(f"Error while getting push notification info: {e}")
            return GetTaskPushNotificationResponse(
                id=request.id,
                error=InternalError(
                    message="An error occurred while getting push notification info"
                ),
            )

        return GetTaskPushNotificationResponse(
            id=request.id,
            result=TaskPushNotificationConfig(
                id=task_params.id, pushNotificationConfig=notification_info
            ),
        )

    async def upsert_task(self, task_send_params: TaskSendParams) -> Task:
        logger.info(f"Upserting task {task_send_params.id}")
        async with self.lock:
            task = self.tasks.get(task_send_params.id)
            if task is None:
                task = Task(
                    id=task_send_params.id,
                    sessionId=task_send_params.sessionId,
                    messages=[task_send_params.message],
                    status=TaskStatus(state=TaskState.SUBMITTED),
                    history=[task_send_params.message],
                )
                self.tasks[task_send_params.id] = task
            else:
                task.history.append(task_send_params.message)

            # -----------------------------------------------------------------
            # Persist optional user / agent information into task.metadata
            # -----------------------------------------------------------------
            if task_send_params.metadata:
                # Ensure metadata dict exists
                if task.metadata is None:
                    task.metadata = {}
                # Merge (new keys override old)
                task.metadata.update(task_send_params.metadata)

            return task

    # ---------------------------------------------------------------------
    # Extended querying capabilities required by BaseTaskManager
    # ---------------------------------------------------------------------

    async def on_get_tasks_by_user(self, user_id: str) -> list[Task]:
        """
        Return all tasks that have `metadata['user_id'] == user_id`.
        """
        async with self.lock:
            return [
                task
                for task in self.tasks.values()
                if task.metadata and task.metadata.get("user_id") == user_id
            ]

    async def on_get_tasks_by_agent(self, agent_id: str) -> list[Task]:
        """
        Return all tasks that have `metadata['agent_id'] == agent_id`.
        """
        async with self.lock:
            return [
                task
                for task in self.tasks.values()
                if task.metadata and task.metadata.get("agent_id") == agent_id
            ]

    async def on_resubscribe_to_task(
        self, request: TaskResubscriptionRequest
    ) -> AsyncIterable[SendTaskStreamingResponse] | JSONRPCResponse:
        return new_not_implemented_error(request.id)

    async def update_store(
        self, task_id: str, status: TaskStatus, artifacts: list[Artifact]
    ) -> Task:
        async with self.lock:
            try:
                task = self.tasks[task_id]
            except KeyError:
                logger.error(f"Task {task_id} not found for updating the task")
                raise ValueError(f"Task {task_id} not found")

            task.status = status

            if status.message is not None:
                task.history.append(status.message)

            if artifacts is not None:
                if task.artifacts is None:
                    task.artifacts = []
                task.artifacts.extend(artifacts)

            return task

    def append_task_history(self, task: Task, historyLength: int | None):
        new_task = task.model_copy()
        if historyLength is not None and historyLength > 0:
            new_task.history = new_task.history[-historyLength:]
        else:
            new_task.history = []

        return new_task

    async def setup_sse_consumer(self, task_id: str, is_resubscribe: bool = False):
        async with self.subscriber_lock:
            if task_id not in self.task_sse_subscribers:
                if is_resubscribe:
                    raise ValueError("Task not found for resubscription")
                self.task_sse_subscribers[task_id] = []

            sse_event_queue = asyncio.Queue(maxsize=0)  # <=0 is unlimited
            self.task_sse_subscribers[task_id].append(sse_event_queue)
            return sse_event_queue

    async def enqueue_events_for_sse(self, task_id, task_update_event):
        async with self.subscriber_lock:
            if task_id not in self.task_sse_subscribers:
                return

            current_subscribers = self.task_sse_subscribers[task_id]
            for subscriber in current_subscribers:
                await subscriber.put(task_update_event)

    async def dequeue_events_for_sse(
        self, request_id, task_id, sse_event_queue: asyncio.Queue
    ) -> AsyncIterable[SendTaskStreamingResponse] | JSONRPCResponse:
        try:
            while True:
                event = await sse_event_queue.get()
                if isinstance(event, JSONRPCError):
                    yield SendTaskStreamingResponse(id=request_id, error=event)
                    break

                yield SendTaskStreamingResponse(id=request_id, result=event)
                if isinstance(event, TaskStatusUpdateEvent) and event.final:
                    break
        finally:
            async with self.subscriber_lock:
                if task_id in self.task_sse_subscribers:
                    self.task_sse_subscribers[task_id].remove(sse_event_queue)
