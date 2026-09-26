"""AgentArea's A2A request handler: the SDK's typed calls onto our task system.

The SDK's ``JsonRpcDispatcher`` owns the protocol -- JSON-RPC framing, parsing
params into ``a2a.types``, error codes, SSE and the ``A2A-Version`` check. This
adapter maps each typed call onto the task service, the task event feed and
push-config storage, for the one agent named in the URL. Who is calling and
which agent they addressed arrive in ``ServerCallContext.state`` via
:class:`AgentAreaCallContextBuilder`.
"""

import logging
import time
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import TracebackType
from typing import Any
from uuid import UUID

from a2a.auth.user import User
from a2a.server.context import ServerCallContext
from a2a.server.events.event_queue import Event
from a2a.server.request_handlers import RequestHandler, validate_request_params
from a2a.server.routes import DefaultServerCallContextBuilder
from a2a.types import (
    AgentCard,
    CancelTaskRequest,
    DeleteTaskPushNotificationConfigRequest,
    GetExtendedAgentCardRequest,
    GetTaskPushNotificationConfigRequest,
    GetTaskRequest,
    ListTaskPushNotificationConfigsRequest,
    ListTaskPushNotificationConfigsResponse,
    ListTasksRequest,
    ListTasksResponse,
    Message,
    SendMessageRequest,
    SubscribeToTaskRequest,
    Task,
    TaskPushNotificationConfig,
    TaskState,
)
from a2a.utils.constants import DEFAULT_LIST_TASKS_PAGE_SIZE
from a2a.utils.errors import (
    A2AError,
    InternalError,
    InvalidParamsError,
    InvalidRequestError,
    TaskNotCancelableError,
    TaskNotFoundError,
    UnsupportedOperationError,
)
from a2a.utils.task import decode_page_token, encode_page_token, validate_page_size
from agentarea_agents.application.agent_service import AgentService
from agentarea_api.api.v1._task_authority import assert_may_act_on_task
from agentarea_api.api.v1.a2a_auth import A2AAuthContext
from agentarea_api.api.v1.a2a_card import build_agent_card
from agentarea_api.api.v1.a2a_mapping import (
    TERMINAL_EVENT_TYPES,
    TERMINAL_STATES,
    build_agent_task,
    context_id_for,
    message_text,
    task_state,
    to_a2a_task,
    workflow_event_to_a2a,
)
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.context_manager import ContextManager
from agentarea_common.events.task_stream import TaskEventEnvelope
from agentarea_common.infrastructure.secret_manager import BaseSecretManager
from agentarea_common.utils.a2a_push import (
    delete_push_config,
    get_push_config,
    list_push_configs,
    push_token_secret_name,
    task_push_config_result,
    upsert_push_config,
)
from agentarea_common.utils.url_safety import UnsafeUrlError, validate_outbound_url
from agentarea_tasks.domain.models import AgentTask, TaskUpdate
from agentarea_tasks.task_service import TaskService
from google.protobuf.json_format import MessageToDict
from starlette.requests import Request

logger = logging.getLogger(__name__)

A2A_SCOPE_KEY = "agentarea.a2a"
_AVAILABLE_AGENT_STATUSES = frozenset({"active", "available", "ready"})

TaskEventFeed = Callable[..., AsyncIterator[TaskEventEnvelope]]


@dataclass(frozen=True)
class A2ACallScope:
    """What the route resolved before handing the request to the SDK."""

    agent_id: UUID
    auth: A2AAuthContext
    base_url: str


class _A2AUser(User):
    def __init__(self, auth: A2AAuthContext):
        self._auth = auth

    @property
    def is_authenticated(self) -> bool:
        return self._auth.authenticated

    @property
    def user_name(self) -> str:
        return self._auth.user_id or ""


class AgentAreaCallContextBuilder(DefaultServerCallContextBuilder):
    """Lift the route's :class:`A2ACallScope` into ``ServerCallContext.state``."""

    def build(self, request: Request) -> ServerCallContext:
        context = super().build(request)
        context.state[A2A_SCOPE_KEY] = request.state.a2a_scope
        return context

    def build_user(self, request: Request) -> User:
        return _A2AUser(request.state.a2a_scope.auth)


def log_a2a_operation(
    operation: str,
    agent_id: UUID,
    auth_context: A2AAuthContext,
    request_id: str | int | None = None,
    task_id: UUID | str | None = None,
    status: str = "started",
    duration_ms: float | None = None,
    error: str | None = None,
    extra_metadata: dict[str, Any] | None = None,
) -> None:
    """Log an A2A operation with structured ``a2a_metrics`` for monitoring."""
    log_data: dict[str, Any] = {
        "a2a_operation": operation,
        "agent_id": str(agent_id),
        "request_id": request_id,
        "status": status,
        "auth_method": auth_context.auth_method,
        "authenticated": auth_context.authenticated,
        "user_id": auth_context.user_id,
        "workspace_id": auth_context.workspace_id,
        "permissions": auth_context.permissions,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    if task_id:
        log_data["task_id"] = str(task_id)
    if duration_ms is not None:
        log_data["duration_ms"] = duration_ms
    if error:
        log_data["error"] = error
    client_metadata = {
        key: auth_context.metadata[key]
        for key in ("user_agent", "client_ip", "forwarded_for")
        if auth_context.metadata.get(key)
    }
    if client_metadata:
        log_data["client_metadata"] = client_metadata
    if extra_metadata:
        log_data.update(extra_metadata)

    if status == "failed" or error:
        logger.error(f"A2A {operation} failed", extra={"a2a_metrics": log_data})
    elif status == "completed":
        logger.info(f"A2A {operation} completed", extra={"a2a_metrics": log_data})
    else:
        logger.info(f"A2A {operation} {status}", extra={"a2a_metrics": log_data})


@dataclass
class _Operation:
    """Structured started/completed/failed logging around one handler call."""

    name: str
    scope: A2ACallScope
    context: ServerCallContext
    task_id: UUID | str | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    _started: float = 0.0

    def _log(self, status: str, error: str | None = None) -> None:
        log_a2a_operation(
            self.name,
            self.scope.agent_id,
            self.scope.auth,
            self.context.state.get("request_id"),
            self.task_id,
            status=status,
            duration_ms=None if status == "started" else (time.monotonic() - self._started) * 1000,
            error=error,
            extra_metadata=self.extra or None,
        )

    def __enter__(self) -> "_Operation":
        self._started = time.monotonic()
        self._log("started")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if exc is None:
            self._log("completed")
        elif isinstance(exc, A2AError):
            self._log("failed", error=exc.message)
        elif isinstance(exc, Exception):
            self._log("failed", error=str(exc))
        else:
            # GeneratorExit / CancelledError: the client went away mid-stream.
            self._log("closed")


def _scope(context: ServerCallContext) -> A2ACallScope:
    return context.state[A2A_SCOPE_KEY]


def _user_context(scope: A2ACallScope) -> UserContext:
    """The caller as a workspace member; A2A serves only authenticated users."""
    auth = scope.auth
    if not auth.authenticated or not auth.user_id or not auth.workspace_id:
        raise InvalidRequestError(message="A2A requests require an authenticated user")
    user_context = UserContext(
        user_id=auth.user_id,
        workspace_id=auth.workspace_id,
        workspace_slug=auth.workspace_slug,
    )
    ContextManager.set_context(user_context)
    return user_context


def _task_uuid(raw: str) -> UUID:
    try:
        return UUID(raw)
    except ValueError as e:
        raise InvalidParamsError(message=f"Invalid task ID: {raw}") from e


class AgentAreaRequestHandler(RequestHandler):
    """A2A calls for one agent, served from the task service and event feed."""

    def __init__(
        self,
        *,
        task_service: TaskService,
        agent_service: AgentService,
        secret_manager: BaseSecretManager,
        event_feed: TaskEventFeed,
    ):
        self._tasks = task_service
        self._agents = agent_service
        self._secrets = secret_manager
        self._event_feed = event_feed

    # -- helpers -----------------------------------------------------------

    async def _owned_task(self, raw_id: str, scope: A2ACallScope, *, live: bool) -> AgentTask:
        """The task, which must belong to the agent this endpoint serves."""
        task_id = _task_uuid(raw_id)
        task = (
            await self._tasks.get_task_with_workflow_status(task_id)
            if live
            else await self._tasks.get_task(task_id)
        )
        if task is None or str(task.agent_id) != str(scope.agent_id):
            raise TaskNotFoundError(message=f"Task not found: {raw_id}")
        return task

    async def _task_to_act_on(
        self, raw_id: str, scope: A2ACallScope, user: UserContext, *, live: bool
    ) -> AgentTask:
        """An owned task the caller may act on: they started it, or administer the workspace.

        The same run authority the REST task endpoints enforce. Its refusal is an
        ``HTTPException(403)``, which ``JsonRpcDispatcher`` re-raises instead of
        folding into a JSON-RPC error, so the caller gets the same 403 as REST.
        """
        task = await self._owned_task(raw_id, scope, live=live)
        await assert_may_act_on_task(task, user)
        return task

    async def _require_available_agent(self, agent_id: UUID) -> Any:
        agent = await self._agents.get(agent_id)
        if agent is None:
            raise InvalidParamsError(message=f"Agent with ID {agent_id} does not exist")
        if agent.status and agent.status.lower() not in _AVAILABLE_AGENT_STATUSES:
            raise InvalidParamsError(
                message=f"Agent {agent.name} (ID: {agent_id}) is not available "
                f"(status: {agent.status})"
            )
        return agent

    async def _register_push_config(
        self, task: AgentTask, config: TaskPushNotificationConfig
    ) -> dict[str, Any]:
        """Persist a webhook: url in task parameters, token in the secret store."""
        if not config.url:
            raise InvalidParamsError(message="Push notification config url is required")
        if config.HasField("authentication"):
            raise InvalidParamsError(
                message="Push notification authentication schemes are not supported; "
                "send a token instead"
            )
        try:
            validate_outbound_url(config.url)
        except UnsafeUrlError as e:
            raise InvalidParamsError(message=f"Unsafe webhook url: {e}") from e

        new_params, stored = upsert_push_config(task.task_parameters, config.url, config.id or None)
        if config.token:
            await self._secrets.set_secret(
                push_token_secret_name(str(task.id), stored["id"]), config.token
            )
        await self._tasks.task_repository.update_by_id(
            task.id, TaskUpdate(task_parameters=new_params)
        )
        return stored

    async def _submit(
        self, params: SendMessageRequest, context: ServerCallContext, op: _Operation
    ) -> AgentTask:
        scope = op.scope
        user = _user_context(scope)
        await self._require_available_agent(scope.agent_id)

        text = message_text(params.message)
        if not text.strip():
            raise InvalidParamsError(message="Message must contain non-empty text content")

        task = build_agent_task(
            message=params.message,
            metadata=MessageToDict(params.metadata),
            agent_id=scope.agent_id,
            auth=scope.auth,
            user_id=user.user_id,
            workspace_id=user.workspace_id,
            method=context.state["method"],
            request_id=context.state.get("request_id"),
        )
        try:
            created = await self._tasks.submit_task(task)
        except ValueError as e:
            logger.warning(
                "A2A task submission for agent %s rejected: %s", scope.agent_id, e, exc_info=True
            )
            raise InvalidParamsError(message="Invalid parameters") from e

        op.task_id = created.id
        op.extra.update(
            {
                "task_title": created.title,
                "task_status": created.status,
                "message_length": len(text),
                "message_parts_count": len(params.message.parts),
            }
        )

        push = params.configuration.task_push_notification_config
        if params.configuration.HasField("task_push_notification_config") and push.url:
            try:
                await self._register_push_config(created, push)
            except InvalidParamsError:
                logger.warning(
                    "Ignoring invalid inline push notification config for task %s",
                    created.id,
                    exc_info=True,
                )
        return created

    async def _follow(self, task: AgentTask) -> AsyncGenerator[Event]:
        """Stream the task's events (catch-up, then live) until it is terminal."""
        task_id = str(task.id)
        context_id = context_id_for(task)
        async for env in self._event_feed(
            task.id,
            workspace_id=str(task.workspace_id),
            terminal_types=TERMINAL_EVENT_TYPES,
        ):
            events, terminal = workflow_event_to_a2a(
                env.event_type, env.data, task_id=task_id, context_id=context_id
            )
            for event in events:
                yield event
            if terminal:
                return

    # -- messages ----------------------------------------------------------

    @validate_request_params
    async def on_message_send(
        self, params: SendMessageRequest, context: ServerCallContext
    ) -> Task | Message:
        # Non-blocking whatever ``returnImmediately`` says: an agent run can
        # outlast any proxy timeout, so the result is read by GetTask, a
        # stream, or a push notification.
        with _Operation("message_send", _scope(context), context) as op:
            return to_a2a_task(await self._submit(params, context, op))

    @validate_request_params
    async def on_message_send_stream(
        self, params: SendMessageRequest, context: ServerCallContext
    ) -> AsyncGenerator[Event]:
        scope = _scope(context)
        with _Operation("message_stream", scope, context) as op:
            created = await self._submit(params, context, op)
            yield to_a2a_task(created)
            async for event in self._follow(created):
                yield event

    # -- tasks -------------------------------------------------------------

    @validate_request_params
    async def on_get_task(self, params: GetTaskRequest, context: ServerCallContext) -> Task | None:
        scope = _scope(context)
        with _Operation("task_get", scope, context, task_id=params.id) as op:
            _user_context(scope)
            task = await self._owned_task(params.id, scope, live=True)
            op.extra["task_status"] = task.status
            return to_a2a_task(task)

    @validate_request_params
    async def on_list_tasks(
        self, params: ListTasksRequest, context: ServerCallContext
    ) -> ListTasksResponse:
        scope = _scope(context)
        with _Operation("task_list", scope, context):
            _user_context(scope)
            if params.context_id or params.status or params.HasField("status_timestamp_after"):
                raise UnsupportedOperationError(
                    message="ListTasks filters (contextId, status, statusTimestampAfter) "
                    "are not supported"
                )
            page_size = (
                params.page_size if params.HasField("page_size") else DEFAULT_LIST_TASKS_PAGE_SIZE
            )
            validate_page_size(page_size)
            offset = 0
            if params.page_token:
                cursor = decode_page_token(params.page_token)
                if not cursor.isdigit():
                    raise InvalidParamsError(message="Invalid page token")
                offset = int(cursor)

            tasks = await self._tasks.get_agent_tasks(
                scope.agent_id, limit=page_size, offset=offset
            )
            total = await self._tasks.count_agent_tasks(scope.agent_id)
            end = offset + len(tasks)
            return ListTasksResponse(
                tasks=[to_a2a_task(task) for task in tasks],
                next_page_token=encode_page_token(str(end)) if end < total else "",
                page_size=page_size,
                total_size=total,
            )

    @validate_request_params
    async def on_cancel_task(
        self, params: CancelTaskRequest, context: ServerCallContext
    ) -> Task | None:
        scope = _scope(context)
        with _Operation("task_cancel", scope, context, task_id=params.id) as op:
            user = _user_context(scope)
            task = await self._task_to_act_on(params.id, scope, user, live=True)
            op.extra["previous_status"] = task.status
            if task_state(task.status) in TERMINAL_STATES:
                raise TaskNotCancelableError(
                    message=f"Task cannot be cancelled (current status: {task.status})"
                )
            if not await self._tasks.cancel_task(task.id):
                raise InternalError(message="Task cancellation failed")
            updated = await self._tasks.get_task_with_workflow_status(task.id)
            return to_a2a_task(updated or task)

    @validate_request_params
    async def on_subscribe_to_task(
        self, params: SubscribeToTaskRequest, context: ServerCallContext
    ) -> AsyncGenerator[Event]:
        scope = _scope(context)
        with _Operation("task_subscribe", scope, context, task_id=params.id):
            _user_context(scope)
            task = await self._owned_task(params.id, scope, live=True)
            state = task_state(task.status)
            if state in TERMINAL_STATES:
                raise UnsupportedOperationError(
                    message=f"Task {task.id} is in terminal state {TaskState.Name(state)}"
                )
            yield to_a2a_task(task)
            async for event in self._follow(task):
                yield event

    # -- push notification configs ----------------------------------------

    @validate_request_params
    async def on_create_task_push_notification_config(
        self, params: TaskPushNotificationConfig, context: ServerCallContext
    ) -> TaskPushNotificationConfig:
        scope = _scope(context)
        with _Operation("push_config_create", scope, context, task_id=params.task_id):
            user = _user_context(scope)
            if not params.task_id:
                raise InvalidParamsError(message="Push notification config taskId is required")
            task = await self._task_to_act_on(params.task_id, scope, user, live=False)
            stored = await self._register_push_config(task, params)
            return task_push_config_result(str(task.id), stored)

    @validate_request_params
    async def on_get_task_push_notification_config(
        self, params: GetTaskPushNotificationConfigRequest, context: ServerCallContext
    ) -> TaskPushNotificationConfig:
        scope = _scope(context)
        with _Operation("push_config_get", scope, context, task_id=params.task_id):
            user = _user_context(scope)
            task = await self._task_to_act_on(params.task_id, scope, user, live=False)
            config = get_push_config(task.task_parameters, params.id)
            if config is None:
                raise TaskNotFoundError(message="Push notification config not found")
            return task_push_config_result(str(task.id), config)

    @validate_request_params
    async def on_list_task_push_notification_configs(
        self, params: ListTaskPushNotificationConfigsRequest, context: ServerCallContext
    ) -> ListTaskPushNotificationConfigsResponse:
        scope = _scope(context)
        with _Operation("push_config_list", scope, context, task_id=params.task_id):
            user = _user_context(scope)
            task = await self._task_to_act_on(params.task_id, scope, user, live=False)
            return ListTaskPushNotificationConfigsResponse(
                configs=[
                    task_push_config_result(str(task.id), config)
                    for config in list_push_configs(task.task_parameters)
                ]
            )

    @validate_request_params
    async def on_delete_task_push_notification_config(
        self, params: DeleteTaskPushNotificationConfigRequest, context: ServerCallContext
    ) -> None:
        scope = _scope(context)
        with _Operation("push_config_delete", scope, context, task_id=params.task_id):
            user = _user_context(scope)
            task = await self._task_to_act_on(params.task_id, scope, user, live=False)
            new_params, removed = delete_push_config(task.task_parameters, params.id)
            if not removed:
                return
            await self._tasks.task_repository.update_by_id(
                task.id, TaskUpdate(task_parameters=new_params)
            )
            secret_name = push_token_secret_name(str(task.id), params.id)
            try:
                await self._secrets.delete_secret(secret_name)
            except Exception:
                # The config is gone, so the token can no longer be sent; a
                # leftover secret is reclaimed with the task's other secrets.
                logger.warning(
                    "Could not delete A2A push token secret %s", secret_name, exc_info=True
                )

    # -- agent card --------------------------------------------------------

    @validate_request_params
    async def on_get_extended_agent_card(
        self, params: GetExtendedAgentCardRequest, context: ServerCallContext
    ) -> AgentCard:
        scope = _scope(context)
        with _Operation("agent_card", scope, context):
            _user_context(scope)
            agent = await self._require_available_agent(scope.agent_id)
            return build_agent_card(
                agent, base_url=scope.base_url, agent_id=scope.agent_id, extended=True
            )
