"""The platform MCP server is an MCP Events server (SEP-3415): every stream the caller may read.

``install_mcp_events`` is the one place the extension touches the MCP SDK: it
registers ``events/list``, ``events/poll``, ``events/subscribe`` and
``events/unsubscribe`` and advertises the extension on ``initialize`` and
``server/discover``, both as ``capabilities.extensions`` and as the pre-SEP
top-level ``capabilities.events`` a deployed client reads. The SDK's wire
models drop unknown capability keys, so that is added after serialization.

An event type is a stream, named ``<workspace slug>/<stream id>`` on every
mount. The mount decides which workspaces a caller reaches: the pinned one
(``/mcp/w/{workspace}``), the client's (``/mcp/clients/{id}``), or every one
the caller belongs to (``/mcp``). Who may poll or subscribe is who may read the
stream (``StreamReaders``). The mounts are stateless, so there is no push
(``events/stream``): poll and webhook only.
"""

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

from agentarea_agents_sdk.mcp_server.auth import get_mcp_user_context
from agentarea_common.auth.context import UserContext, WorkspaceUnreachableError
from agentarea_common.auth.dependencies import enter_workspace
from agentarea_common.auth.permission import PermissionService
from agentarea_common.base import RepositoryFactory
from agentarea_common.base.tenant_scope import workspace_scope
from agentarea_common.config import get_database, get_settings
from agentarea_common.di.container import resolve
from agentarea_common.workspaces.lookup import workspace_slug_for
from agentarea_secrets.secret_manager_factory import get_real_secret_manager
from agentarea_streams.application.events_poll import head_position, read_page
from agentarea_streams.application.external_subscriptions import ExternalSubscriptions
from agentarea_streams.application.stream_access import StreamReaders
from agentarea_streams.application.stream_service import StreamService
from agentarea_streams.application.webhook_endpoint import WebhookEndpoint
from agentarea_streams.domain.errors import StreamNotFoundError
from agentarea_streams.domain.mcp_events import (
    DEFAULT_MAX_EVENTS,
    DEFAULT_TTL,
    DELIVERY_MODES,
    EXTENSION_ID,
    MAX_EVENTS,
    NEXT_POLL_MS,
    SKETCH_CAPABILITY,
    ErrorCode,
    EventArguments,
    EventsError,
    PollCursor,
    event_name,
    input_schema,
    occurrence,
    parse_event_name,
    payload_schema,
)
from agentarea_streams.infrastructure.event_repository import StreamEventRepository
from mcp.server.lowlevel import Server
from mcp.shared.exceptions import MCPError
from mcp_types import RequestParams
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

SETTINGS = {"listChanged": False}
_ADVERTISED_ON = frozenset({"initialize", "server/discover"})


class EventsScope(Protocol):
    """The workspaces one mount serves to the caller."""

    async def workspaces(self) -> list[UserContext]: ...

    async def enter(self, workspace: str) -> UserContext: ...


class PinnedScope:
    """``/mcp/w/{workspace}``: the workspace the URL pinned, entered by the auth middleware."""

    async def workspaces(self) -> list[UserContext]:
        return [get_mcp_user_context()]

    async def enter(self, workspace: str) -> UserContext:
        context: UserContext = get_mcp_user_context()
        if workspace not in (context.workspace_slug, context.workspace_id):
            raise EventsError(ErrorCode.NOT_FOUND, "no such event type here", {"kind": "event"})
        return context


class SpanningScope:
    """``/mcp``: every workspace the caller reaches; the event name says which."""

    async def workspaces(self) -> list[UserContext]:
        from agentarea_api.api.v1.workspaces import get_workspace_service, list_reachable_workspaces

        principal = get_mcp_user_context()
        async with get_database().async_session_factory() as session:
            reachable = await list_reachable_workspaces(
                principal, get_workspace_service(session, principal)
            )
        return [await enter_workspace(principal, workspace.id) for workspace in reachable]

    async def enter(self, workspace: str) -> UserContext:
        try:
            return await enter_workspace(get_mcp_user_context(), workspace)
        except WorkspaceUnreachableError:
            raise EventsError(
                ErrorCode.FORBIDDEN, f"no accessible workspace {workspace!r}"
            ) from None


class ClientScope:
    """``/mcp/clients/{id}``: the client's workspace, as its caller."""

    def __init__(self, context: Callable[[], Awaitable[UserContext | None]]):
        self._context = context

    async def _client_context(self) -> UserContext:
        context = await self._context()
        if context is None:
            raise EventsError(ErrorCode.FORBIDDEN, "not authorized for this client")
        return context

    async def workspaces(self) -> list[UserContext]:
        return [await self._client_context()]

    async def enter(self, workspace: str) -> UserContext:
        context = await self._client_context()
        if workspace not in (context.workspace_slug, context.workspace_id):
            raise EventsError(ErrorCode.NOT_FOUND, "no such event type here", {"kind": "event"})
        return context


class ListParams(RequestParams):
    cursor: str | None = None


class PollParams(RequestParams):
    name: str
    arguments: dict[str, Any] | None = None
    cursor: str | None = None
    max_age_ms: int | None = Field(default=None, ge=0)
    max_events: int | None = Field(default=None, ge=1)


class WebhookDelivery(BaseModel):
    mode: str = "webhook"
    url: str
    secret: str


class SubscribeParams(RequestParams):
    name: str
    arguments: dict[str, Any] | None = None
    delivery: WebhookDelivery
    cursor: str | None = None
    max_age_ms: int | None = Field(default=None, ge=0)
    ttl_ms: int | None = Field(default=None, ge=0)


class UnsubscribeDelivery(BaseModel):
    url: str


class UnsubscribeParams(RequestParams):
    name: str
    arguments: dict[str, Any] | None = None
    delivery: UnsubscribeDelivery


def subscriber_of(context: UserContext) -> str:
    """The principal a webhook subscription is keyed by: the key, the client, or the user."""
    if context.credential is not None and context.credential.key_id:
        return f"key:{context.credential.key_id}"
    if context.client_id:
        return f"client:{context.client_id}"
    return f"user:{context.user_id}"


def _arguments(raw: dict[str, Any] | None) -> EventArguments:
    try:
        return EventArguments.model_validate(raw or {})
    except ValidationError as error:
        raise EventsError(
            ErrorCode.INVALID_PARAMS, "arguments do not match the event's inputSchema"
        ) from error


def _utcnow() -> datetime:
    return datetime.now(UTC)


@asynccontextmanager
async def _session(context: UserContext, *, write: bool) -> AsyncIterator[AsyncSession]:
    database = get_database()
    with workspace_scope(context.workspace_id):
        async with database.session() if write else database.read_session() as session:
            yield session


class MCPEvents:
    def __init__(self, scope: EventsScope, *, endpoint: WebhookEndpoint | None = None):
        self._scope = scope
        self._endpoint = endpoint or WebhookEndpoint()

    @staticmethod
    def _readers() -> StreamReaders:
        return StreamReaders(resolve(PermissionService))

    @staticmethod
    def _service(session: AsyncSession, context: UserContext) -> StreamService:
        return StreamService(RepositoryFactory(session, context), get_settings().streams)

    async def _open(self, name: str) -> tuple[UserContext, UUID]:
        workspace, stream_id = parse_event_name(name)
        context = await self._scope.enter(workspace)
        async with _session(context, write=False) as session:
            try:
                await self._service(session, context).get_stream(stream_id)
            except StreamNotFoundError:
                raise EventsError(
                    ErrorCode.NOT_FOUND, f"no event type {name!r}", {"kind": "event"}
                ) from None
        if not await self._readers().may_read(context.user_id, stream_id):
            raise EventsError(ErrorCode.FORBIDDEN, "you may not read this stream")
        return context, stream_id

    async def list(self, _params: ListParams) -> dict[str, Any]:
        readers = self._readers()
        events: list[dict[str, Any]] = []
        for context in await self._scope.workspaces():
            slug = context.workspace_slug or await workspace_slug_for(context.workspace_id)
            readable = await readers.readable(context.user_id)
            async with _session(context, write=False) as session:
                streams = await self._service(session, context).list_streams(
                    limit=1000, offset=0, ids=readable
                )
            events.extend(
                {
                    "name": event_name(slug, stream.id),
                    "title": stream.name,
                    "description": stream.description or f"Events of the stream {stream.name}",
                    "delivery": list(DELIVERY_MODES),
                    "inputSchema": input_schema(),
                    "payloadSchema": payload_schema(),
                }
                for stream in streams
            )
        return {"events": events}

    async def poll(self, params: PollParams) -> dict[str, Any]:
        context, stream_id = await self._open(params.name)
        event_filter = _arguments(params.arguments).to_filter()
        now = _utcnow()
        window_start = now - get_settings().streams.RETENTION
        async with _session(context, write=False) as session:
            events = StreamEventRepository(session, context)
            if params.cursor is None:
                head = await head_position(events, stream_id)
                return {
                    "events": [],
                    "cursor": PollCursor(at=now, sequence=head).encode(),
                    "truncated": False,
                    "hasMore": False,
                    "nextPollMs": NEXT_POLL_MS,
                }
            cursor = PollCursor.decode(params.cursor)
            since = window_start
            truncated = cursor.before(window_start)
            if params.max_age_ms is not None:
                age_floor = now - timedelta(milliseconds=params.max_age_ms)
                truncated = truncated or cursor.before(age_floor)
                since = max(since, age_floor)
            page = await read_page(
                events,
                stream_id,
                after=cursor.sequence,
                since=since,
                admits=event_filter.admits,
                max_events=min(params.max_events or DEFAULT_MAX_EVENTS, MAX_EVENTS),
            )
        return {
            "events": [occurrence(event, params.name) for event in page.events],
            "cursor": PollCursor(at=now, sequence=page.position).encode(),
            "truncated": truncated,
            "hasMore": page.has_more,
            "nextPollMs": NEXT_POLL_MS,
        }

    async def subscribe(self, params: SubscribeParams) -> dict[str, Any]:
        if params.delivery.mode != "webhook":
            raise EventsError(
                ErrorCode.UNSUPPORTED,
                "events/subscribe serves webhook delivery only",
                {"feature": "deliveryMode", "value": params.delivery.mode},
            )
        context, stream_id = await self._open(params.name)
        arguments = _arguments(params.arguments)
        ttl_ms = (
            params.ttl_ms
            if "ttl_ms" in params.model_fields_set
            else int(DEFAULT_TTL.total_seconds() * 1000)
        )
        async with _session(context, write=True) as session:
            subscriptions = ExternalSubscriptions(
                self._service(session, context),
                get_real_secret_manager(session=session, user_context=context),
                self._endpoint,
            )
            subscribed = await subscriptions.subscribe(
                stream_id=stream_id,
                subscriber=subscriber_of(context),
                url=params.delivery.url,
                secret=params.delivery.secret,
                arguments=arguments,
                ttl_ms=ttl_ms,
            )
        result: dict[str, Any] = {
            "id": subscribed.id,
            "refreshBefore": subscribed.refresh_before.isoformat(),
            # Webhook deliveries are not replayed: a cursor is served by poll only.
            "cursor": None,
            "truncated": params.cursor is not None,
        }
        if subscribed.delivery_status is not None:
            result["deliveryStatus"] = subscribed.delivery_status
        return result

    async def unsubscribe(self, params: UnsubscribeParams) -> dict[str, Any]:
        context, stream_id = await self._open(params.name)
        arguments = _arguments(params.arguments)
        async with _session(context, write=True) as session:
            await ExternalSubscriptions(
                self._service(session, context),
                get_real_secret_manager(session=session, user_context=context),
                self._endpoint,
            ).unsubscribe(
                stream_id=stream_id,
                subscriber=subscriber_of(context),
                url=params.delivery.url,
                arguments=arguments,
            )
        return {}


def _answering(method: Callable[[Any], Awaitable[dict[str, Any]]]):
    async def handler(_ctx: Any, params: Any) -> dict[str, Any]:
        try:
            return await method(params)
        except EventsError as error:
            raise MCPError(code=int(error.code), message=error.message, data=error.data) from None

    return handler


async def _advertise(ctx: Any, call_next: Any) -> Any:
    result = await call_next(ctx)
    if ctx.method in _ADVERTISED_ON and isinstance(result, dict):
        capabilities = result.setdefault("capabilities", {})
        capabilities.setdefault("extensions", {})[EXTENSION_ID] = dict(SETTINGS)
        capabilities[SKETCH_CAPABILITY] = dict(SETTINGS)
    return result


def install_mcp_events(server: Server[Any], scope: EventsScope) -> None:
    """Serve the events extension on ``server`` for the workspaces ``scope`` reaches."""
    events = MCPEvents(scope)
    server.add_request_handler("events/list", ListParams, _answering(events.list))
    server.add_request_handler("events/poll", PollParams, _answering(events.poll))
    server.add_request_handler("events/subscribe", SubscribeParams, _answering(events.subscribe))
    server.add_request_handler(
        "events/unsubscribe", UnsubscribeParams, _answering(events.unsubscribe)
    )
    server.extensions[EXTENSION_ID] = dict(SETTINGS)
    server.middleware.append(_advertise)
