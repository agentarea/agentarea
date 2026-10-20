"""Streams: named event streams, their sources, subscriptions, events and reactions.

The workspace events feed (``/streams/events``, its live tail ``/streams/events/live``)
is every event of the streams the caller may read: see ``stream_event_feed``.
"""

import logging
from collections.abc import Sequence
from typing import Annotated, Any
from uuid import UUID

from agentarea_api.api.deps.services import BaseSecretManagerDep, SecretCatalogServiceDep
from agentarea_common.artifacts import ArtifactService
from agentarea_common.auth.dependencies import UserContextDep
from agentarea_common.auth.permission import require_permission
from agentarea_common.auth.resource_visibility import readable_resource_ids
from agentarea_common.auth.route_authz import enforced_in_handler, requires, unrestricted
from agentarea_common.base import RepositoryFactoryDep
from agentarea_common.base.pagination import MAX_BIGINT, MAX_OFFSET
from agentarea_common.base.tenant_scope import workspace_scope
from agentarea_common.config import get_settings
from agentarea_common.utils.types import UtcDatetime
from agentarea_streams.application.stream_service import StreamService
from agentarea_streams.domain import (
    ENVELOPE_VERSION,
    ForwardLoopError,
    NotAForwardError,
    RecordedEvent,
    StreamEventNotFoundError,
    StreamInUseError,
    StreamManagedByPlatformError,
    StreamNameTakenError,
    StreamNotFoundError,
    StreamSourceNotFoundError,
    SubscriptionNotFoundError,
)
from agentarea_streams.domain.errors import (
    NotAProcessorError,
    ProcessorCodeError,
    ProcessorLoopError,
)
from agentarea_streams.domain.feed import FeedFilter, RoutedEvent
from agentarea_streams.domain.processing import Processing, ProcessingStatus
from agentarea_streams.domain.source_types import SourceField, SourceTypeEntry
from agentarea_streams.infrastructure.catalog_source_types import CatalogSourceTypeRepository
from agentarea_streams.infrastructure.event_repository import StreamEventRepository
from agentarea_streams.schemas import (
    ForwardCreate,
    ProcessorCreate,
    ProcessorUpdate,
    SourceCreate,
    StreamCreate,
)
from agentarea_tasks.infrastructure.repository import TaskRepository
from agentarea_triggers.infrastructure.reactions import ReactionRepository, verdict_of_status
from agentarea_triggers.infrastructure.repository import TriggerRepository
from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ._icons import CHANNEL_ICON_NAMESPACE, build_icon_url
from ._stream_sources import (
    create_source,
    delete_stream_with_sources,
    public_webhook_url,
    release_source,
)
from .stream_event_feed import (
    FeedEventResponse,
    FeedFacetsResponse,
    WorkspaceEventPage,
    event_notices_hub,
    feed_items,
    iter_live_feed,
    read_feed_item,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/streams", tags=["streams"])


async def get_stream_service(repository_factory: RepositoryFactoryDep) -> StreamService:
    return StreamService(repository_factory, get_settings().streams)


StreamServiceDep = Annotated[StreamService, Depends(get_stream_service)]


async def get_reactions(repository_factory: RepositoryFactoryDep) -> ReactionRepository:
    return repository_factory.create_repository(ReactionRepository)


ReactionsDep = Annotated[ReactionRepository, Depends(get_reactions)]


class StreamResponse(BaseModel):
    id: UUID
    name: str
    description: str
    kind: str
    created_by: str
    created_at: UtcDatetime

    model_config = {"from_attributes": True}


class StreamSourceResponse(BaseModel):
    id: UUID
    kind: str = Field(description="webhook or poll")
    source_type: str | None = Field(description="The catalog slug of GET /streams/source-types.")
    webhook_id: str | None
    webhook_url: str | None = Field(
        description="Public URL the provider posts to; null for a poll source."
    )
    event_templates: dict[str, Any] | None = Field(
        default=None, description="This source's own kind / key / session_key templates."
    )
    polled_at: UtcDatetime | None = None
    poll_error: str | None = None
    registered: bool = Field(
        default=False,
        description="The provider was pointed at webhook_url (entries with a registration).",
    )
    created_at: UtcDatetime


class SourceCreated(StreamSourceResponse):
    issued: dict[str, str] = Field(
        default_factory=dict,
        description="Credentials generated because they were left out; shown this once only.",
    )


class SourceTypeTemplates(BaseModel):
    kind: str | list[str]
    key: str | list[str] | None
    session_key: str | list[str] | None
    sender: str | list[str] | None
    occurred_at: str | list[str] | None


class SourceTypeResponse(BaseModel):
    slug: str
    name: str
    description: str
    icon: str
    icon_url: str | None
    delivery: str = Field(
        description="webhook, poll or both; platform for the platform stream, which no member adds"
    )
    credentials: list[SourceField] = Field(
        description="Secret fields: write-only, held by reference, never returned."
    )
    config: list[SourceField]
    events: list[str] = Field(
        description="What the provider can send, to enable at the provider; not a filter."
    )
    event: SourceTypeTemplates
    verification_scheme: str | None
    verification_header: str | None
    continues_sessions: bool = Field(
        description="Default of a trigger's session.continue for this type."
    )
    replies: bool = Field(description="A task started by its event can answer where it came from.")


def source_response(row: Any) -> StreamSourceResponse:
    return StreamSourceResponse(
        id=row.id,
        kind=row.kind,
        source_type=row.webhook_type,
        webhook_id=row.webhook_id,
        webhook_url=public_webhook_url(row.webhook_id) if row.webhook_id else None,
        event_templates=row.event_templates,
        polled_at=row.polled_at,
        poll_error=row.poll_error,
        registered=bool(
            row.webhook_id and row.registered_url == public_webhook_url(row.webhook_id)
        ),
        created_at=row.created_at,
    )


def source_type_response(entry: SourceTypeEntry) -> SourceTypeResponse:
    verification = entry.verification
    return SourceTypeResponse(
        slug=entry.slug,
        name=entry.name,
        description=entry.description,
        icon=entry.icon,
        icon_url=build_icon_url(CHANNEL_ICON_NAMESPACE, entry.icon),
        delivery=entry.delivery,
        credentials=entry.credentials,
        config=entry.config,
        events=entry.events,
        event=SourceTypeTemplates(
            kind=entry.event.kind,
            key=entry.event.key,
            session_key=entry.event.session_key,
            sender=entry.event.sender,
            occurred_at=entry.event.occurred_at,
        ),
        verification_scheme=verification.scheme if verification else None,
        verification_header=verification.header if verification else None,
        continues_sessions=entry.continues_sessions(),
        replies=entry.reply is not None,
    )


async def source_types(service: StreamService) -> list[SourceTypeResponse]:
    repository = CatalogSourceTypeRepository(service.repository_factory.session)
    return [source_type_response(entry) for entry in await repository.list_entries()]


class SubscriptionResponse(BaseModel):
    id: UUID
    kind: str
    trigger_id: UUID | None
    filter: dict[str, Any]
    output_stream_ids: list[UUID]
    status: str
    code: str | None = Field(
        default=None, description="A processor's Python (def process(event)); null otherwise."
    )
    created_at: UtcDatetime


class OutcomeResponse(BaseModel):
    subscription_id: UUID
    subscription_kind: str
    trigger_id: UUID | None
    event_id: UUID
    verdict: str = Field(
        description="reacted, skipped, error, or batched while it waits in an open batch"
    )
    reason: str | None
    score: float | None
    task_id: UUID | None
    derived_event_ids: list[UUID] = Field(
        description="Events a forward wrote into its output streams, in output-stream order."
    )
    created_at: UtcDatetime


class EventAttachmentResponse(BaseModel):
    name: str
    mime: str | None
    size: int | None
    sha256: str | None
    ref: str = Field(description="A workspace file path, or the provider's reference (JSON).")
    url: str | None = Field(
        description="Download link for a stored file; null for a provider's reference."
    )


class StreamEventResponse(BaseModel):
    """The event envelope (ADR-0040 §2) and how each subscription reacted."""

    sequence: int
    v: int = ENVELOPE_VERSION
    event_id: UUID
    stream_id: UUID
    source_id: UUID | None
    source_type: str | None
    kind: str
    key: str
    session_key: str | None
    sender: str | None
    received_at: UtcDatetime
    occurred_at: UtcDatetime
    depth: int
    correlation_id: str | None
    causation_id: str | None
    data: dict[str, Any] = Field(description="{headers, body, body_ref}: the request as sent.")
    body_url: str | None = Field(description="Download link for data.body_ref; null without one.")
    attachments: list[EventAttachmentResponse]
    outcomes: list[OutcomeResponse] = Field(
        description="One per subscription that took the event; empty means nobody listened."
    )
    processing: Processing | None = Field(
        default=None, description="What the platform did with it; on the workspace feed."
    )


class HandlerResponse(BaseModel):
    """One subscription's reaction to an event, named for the person reading it."""

    subscription_id: UUID
    kind: str = Field(description="trigger, forward, or deleted")
    name: str = Field(description="The trigger's name, or the streams a forward writes to.")
    verdict: str = Field(
        description="reacted, skipped, error, or batched while it waits in an open batch"
    )
    reason: str | None
    task_id: UUID | None
    task_status: str | None
    derived_event_ids: list[UUID]


class StreamEventDetailResponse(StreamEventResponse):
    handlers: list[HandlerResponse] = Field(
        description="One per subscription that reacted so far; the rest are still to come."
    )


class StreamEventPage(BaseModel):
    events: list[StreamEventResponse]
    next_after: int | None = Field(
        default=None,
        description="With ?after=: pass as ?after= for the next page; null at the end.",
    )
    next_before: int | None = Field(
        default=None,
        description="Without ?after=: pass as ?before= for older events; null at the start.",
    )


def _subscription(row: Any) -> SubscriptionResponse:
    return SubscriptionResponse(
        id=row.id,
        kind=row.kind,
        trigger_id=row.trigger_id,
        filter=row.filter or {},
        output_stream_ids=[UUID(str(s)) for s in row.output_stream_ids],
        status=row.status,
        code=row.code,
        created_at=row.created_at,
    )


def outcome_response(row: Any, subscription: Any | None) -> OutcomeResponse:
    """One reaction (a trigger_executions row) of a subscription to a stream event."""
    return OutcomeResponse(
        subscription_id=row.subscription_id,
        subscription_kind=subscription.kind if subscription else "deleted",
        trigger_id=subscription.trigger_id if subscription else row.trigger_id,
        event_id=row.event_id,
        verdict=row.verdict or verdict_of_status(row.status).value,
        reason=row.reason,
        score=row.score,
        task_id=row.task_id,
        derived_event_ids=[UUID(str(e)) for e in row.derived_event_ids or []],
        created_at=row.created_at,
    )


async def _events_with_outcomes(
    service: StreamService,
    reactions: ReactionRepository,
    stream_id: UUID,
    events: Sequence[RecordedEvent],
) -> list[StreamEventResponse]:
    subscriptions = {row.id: row for row in await service.list_subscriptions(stream_id)}
    by_event: dict[UUID, list[OutcomeResponse]] = {}
    for row in await reactions.list_for_events(stream_id, [e.id for e in events]):
        if row.event_id is None or row.subscription_id is None:
            continue
        by_event.setdefault(row.event_id, []).append(
            outcome_response(row, subscriptions.get(row.subscription_id))
        )
    files = EventFileLinks()
    return [
        StreamEventResponse(
            sequence=e.sequence,
            event_id=e.id,
            stream_id=e.stream_id,
            source_id=e.source_id,
            source_type=e.source_type,
            kind=e.type,
            key=e.event_key,
            session_key=e.session_key,
            sender=e.sender,
            received_at=e.received_at,
            occurred_at=e.time,
            depth=e.depth,
            correlation_id=e.correlation_id,
            causation_id=e.causation_id,
            data=e.data,
            body_url=await files.url(e.workspace_id, e.data.get("body_ref")),
            attachments=[
                EventAttachmentResponse(
                    name=a.name,
                    mime=a.mime,
                    size=a.size,
                    sha256=a.sha256,
                    ref=a.ref,
                    url=await files.url(e.workspace_id, a.ref) if a.stored else None,
                )
                for a in e.attachments
            ],
            outcomes=by_event.get(e.id, []),
        )
        for e in events
    ]


async def _event_detail(
    service: StreamService,
    reactions: ReactionRepository,
    user_context: Any,
    event: RecordedEvent,
) -> StreamEventDetailResponse:
    (response,) = await _events_with_outcomes(service, reactions, event.stream_id, [event])
    session = service.repository_factory.session
    routed = await StreamEventRepository(session, user_context).read_routed(event.id)
    if routed is None:
        raise HTTPException(status_code=404, detail=f"Event {event.id} not found")
    (item,) = await feed_items(session, user_context, [routed])
    subscriptions = {row.id: row for row in await service.list_subscriptions(event.stream_id)}
    trigger_names = await TriggerRepository(session, user_context).names(
        [o.trigger_id for o in response.outcomes if o.trigger_id is not None]
    )
    stream_names = {
        row.id: row.name for row in await service.list_streams(limit=1000, offset=0, ids=None)
    }
    task_statuses = await TaskRepository(session, user_context).statuses(
        [o.task_id for o in response.outcomes if o.task_id is not None]
    )
    handlers = []
    for outcome in response.outcomes:
        subscription = subscriptions.get(outcome.subscription_id)
        if outcome.trigger_id is not None:
            name = trigger_names.get(outcome.trigger_id, str(outcome.trigger_id))
        elif subscription is not None:
            name = ", ".join(
                stream_names.get(UUID(str(s)), str(s)) for s in subscription.output_stream_ids
            )
        else:
            name = str(outcome.subscription_id)
        handlers.append(
            HandlerResponse(
                subscription_id=outcome.subscription_id,
                kind=outcome.subscription_kind,
                name=name,
                verdict=outcome.verdict,
                reason=outcome.reason,
                task_id=outcome.task_id,
                task_status=task_statuses.get(outcome.task_id) if outcome.task_id else None,
                derived_event_ids=outcome.derived_event_ids,
            )
        )
    return StreamEventDetailResponse.model_validate(
        {**response.model_dump(), "processing": item.processing, "handlers": handlers}
    )


async def workspace_events(
    service: StreamService,
    reactions: ReactionRepository,
    user_context: Any,
    filters: FeedFilter,
    *,
    before: int | None,
    limit: int,
) -> StreamEventPage:
    """The workspace feed with each event's body and outcomes, for an agent."""
    streams = await _readable_streams(service, user_context.user_id)
    session = service.repository_factory.session
    rows = await StreamEventRepository(session, user_context).read_feed(
        filters, streams, before=before, limit=limit
    )
    processing = {i.event_id: i.processing for i in await feed_items(session, user_context, rows)}
    by_stream: dict[UUID, list[RoutedEvent]] = {}
    for row in rows:
        by_stream.setdefault(row.stream_id, []).append(row)
    full: dict[UUID, StreamEventResponse] = {}
    for stream_id, events in by_stream.items():
        for response in await _events_with_outcomes(service, reactions, stream_id, events):
            response.processing = processing[response.event_id]
            full[response.event_id] = response
    return StreamEventPage(
        events=[full[row.id] for row in rows],
        next_before=rows[-1].sequence if len(rows) == limit else None,
    )


async def _readable_streams(service: StreamService, user_id: str) -> list[UUID]:
    rows = await service.list_streams(
        limit=1000, offset=0, ids=await readable_resource_ids(user_id)
    )
    return [row.id for row in rows]


def feed_filter(
    stream_id: UUID | None = Query(None),
    source_type: str | None = Query(None, max_length=64),
    kind: str | None = Query(
        None, max_length=255, description="An event kind, or a prefix ending in .* (order.*)."
    ),
    sender: str | None = Query(None, max_length=512),
    session_key: str | None = Query(None, max_length=512),
    result: ProcessingStatus | None = Query(None, description="What the platform did with it."),
    since: UtcDatetime | None = Query(None, description="Received at or after."),
    until: UtcDatetime | None = Query(None, description="Received before."),
    platform: bool = Query(
        True,
        description="False leaves out the platform's own events (source type platform); "
        + "the first page's counts still include them.",
    ),
) -> FeedFilter:
    return FeedFilter(
        stream_id=stream_id,
        source_type=source_type,
        kind=kind,
        sender=sender,
        session_key=session_key,
        result=result,
        since=since,
        until=until,
        platform=platform,
    )


FeedFilterDep = Annotated[FeedFilter, Depends(feed_filter)]


class EventFileLinks:
    """Presigned links to an event's stored files; storage is reached only when one exists."""

    EXPIRES_IN = 3600

    def __init__(self) -> None:
        self._service: ArtifactService | None = None

    async def url(self, workspace_id: str, path: Any) -> str | None:
        if not isinstance(path, str) or not path:
            return None
        if self._service is None:
            self._service = ArtifactService()
        return await self._service.presigned_url(workspace_id, path, expires_in=self.EXPIRES_IN)


@router.get(
    "/",
    response_model=list[StreamResponse],
    dependencies=[enforced_in_handler("narrowed to the rows the graph says this caller may read")],
)
async def list_streams(
    user_context: UserContextDep,
    service: StreamServiceDep,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0, le=MAX_OFFSET),
):
    return await service.list_streams(
        limit=limit, offset=offset, ids=await readable_resource_ids(user_context.user_id)
    )


@router.post(
    "/",
    response_model=StreamResponse,
    status_code=201,
    dependencies=[
        unrestricted("workspace member; the workspace-scoped repository is the boundary")
    ],
)
async def create_stream(data: StreamCreate, service: StreamServiceDep):
    try:
        return await service.create_stream(name=data.name, description=data.description)
    except StreamNameTakenError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get(
    "/source-types",
    response_model=list[SourceTypeResponse],
    dependencies=[unrestricted("platform catalogue data, identical for every workspace")],
)
async def list_source_types(service: StreamServiceDep):
    """Source types of the catalog, with the credentials and settings each needs."""
    return await source_types(service)


@router.get(
    "/events",
    response_model=WorkspaceEventPage,
    dependencies=[
        enforced_in_handler("narrowed to the streams the graph says this caller may read")
    ],
)
async def list_workspace_events(
    user_context: UserContextDep,
    service: StreamServiceDep,
    filters: FeedFilterDep,
    before: int | None = Query(
        None, ge=1, le=MAX_BIGINT, description="Newest first, before this sequence."
    ),
    limit: int = Query(50, ge=1, le=200),
):
    """Every event of the workspace's streams the caller may read, newest first.

    Each carries what the platform did with it (``processing``); bodies are
    left out, the event's own endpoint has them.
    """
    streams = await _readable_streams(service, user_context.user_id)
    session = service.repository_factory.session
    events = StreamEventRepository(session, user_context)
    rows = await events.read_feed(filters, streams, before=before, limit=limit)
    facets = None
    if before is None:
        counted = await events.feed_facets(filters, streams)
        facets = FeedFacetsResponse(
            streams=counted.streams,
            source_types=counted.source_types,
            capped=counted.capped,
        )
    return WorkspaceEventPage(
        events=await feed_items(session, user_context, rows),
        next_before=rows[-1].sequence if len(rows) == limit else None,
        facets=facets,
    )


@router.get(
    "/events/live",
    dependencies=[
        enforced_in_handler("narrowed to the streams the graph says this caller may read")
    ],
    responses={200: {"content": {"text/event-stream": {}}}},
)
async def stream_workspace_events(
    user_context: UserContextDep,
    service: StreamServiceDep,
    filters: FeedFilterDep,
):
    """SSE: ``event.recorded`` (a feed item) as an event arrives, ``event.processing``
    ({event_id, processing}) as the platform acts on it. The filters are the feed's;
    ``result`` is not applied here, since an event's result changes as it is handled.
    """
    from agentarea_api.api.deps.database import get_db_session
    from agentarea_api.api.v1.agents_tasks import _with_sse_heartbeats

    streams = await _readable_streams(service, user_context.user_id)
    live_filter = filters.model_copy(update={"result": None})

    async def load(event_id: UUID) -> FeedEventResponse | None:
        # The stream outlives the request whose dependencies bound the workspace.
        with workspace_scope(user_context.workspace_id):
            async with get_db_session() as session:
                return await read_feed_item(session, user_context, live_filter, streams, event_id)

    return StreamingResponse(
        _with_sse_heartbeats(
            iter_live_feed(
                subscribe=lambda: event_notices_hub().subscribe(user_context.workspace_id),
                streams=streams,
                load=load,
            )
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.get(
    "/events/{event_id}",
    response_model=StreamEventDetailResponse,
    dependencies=[enforced_in_handler("read on the stream that holds the event")],
)
async def get_event_by_id(
    event_id: UUID,
    user_context: UserContextDep,
    service: StreamServiceDep,
    reactions: ReactionsDep,
):
    """One event by its id, whichever stream holds it: what a forward or a cause points at."""
    try:
        event = await service.get_event(event_id)
    except StreamEventNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    await require_permission("read", "stream", str(event.stream_id), user_context.user_id)
    return await _event_detail(service, reactions, user_context, event)


@router.get(
    "/{stream_id}",
    response_model=StreamResponse,
    dependencies=[requires("read", "stream", id_param="stream_id")],
)
async def get_stream(stream_id: UUID, service: StreamServiceDep):
    try:
        return await service.get_stream(stream_id)
    except StreamNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.delete(
    "/{stream_id}",
    status_code=204,
    dependencies=[requires("delete", "stream", id_param="stream_id")],
)
async def delete_stream(
    stream_id: UUID,
    service: StreamServiceDep,
    secret_manager: BaseSecretManagerDep,
    secret_catalog: SecretCatalogServiceDep,
):
    """Delete a stream with its events, sources and subscriptions.

    Refused with 409 while a trigger subscribes to it (delete the trigger
    first), or while a forward of any stream writes into it (remove that
    forward first).
    """
    try:
        await delete_stream_with_sources(
            stream_id,
            service=service,
            secret_manager=secret_manager,
            secret_catalog=secret_catalog,
        )
    except StreamNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except (StreamInUseError, StreamManagedByPlatformError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return Response(status_code=204)


@router.get(
    "/{stream_id}/sources",
    response_model=list[StreamSourceResponse],
    dependencies=[requires("read", "stream", id_param="stream_id")],
)
async def list_sources(stream_id: UUID, service: StreamServiceDep):
    return [source_response(row) for row in await service.list_sources(stream_id)]


@router.post(
    "/{stream_id}/sources",
    response_model=SourceCreated,
    status_code=201,
    dependencies=[requires("edit", "stream", id_param="stream_id")],
)
async def add_source(
    stream_id: UUID,
    data: SourceCreate,
    service: StreamServiceDep,
    secret_manager: BaseSecretManagerDep,
    secret_catalog: SecretCatalogServiceDep,
):
    """Add a webhook or poll source of a catalog entry to the stream.

    Credentials are write-only and held by reference; a webhook source's
    response carries the public URL to give the provider.
    """
    try:
        row, issued = await create_source(
            stream_id,
            data,
            service=service,
            secret_manager=secret_manager,
            secret_catalog=secret_catalog,
        )
    except StreamNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except StreamManagedByPlatformError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return SourceCreated(**source_response(row).model_dump(), issued=issued)


@router.delete(
    "/{stream_id}/sources/{source_id}",
    status_code=204,
    dependencies=[requires("edit", "stream", id_param="stream_id")],
)
async def delete_source(
    stream_id: UUID,
    source_id: UUID,
    service: StreamServiceDep,
    secret_manager: BaseSecretManagerDep,
    secret_catalog: SecretCatalogServiceDep,
):
    """Remove a source and its credentials; its events stay."""
    try:
        source = await service.delete_source(stream_id, source_id)
    except StreamSourceNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except StreamManagedByPlatformError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    await release_source(source, secret_manager=secret_manager, secret_catalog=secret_catalog)
    return Response(status_code=204)


@router.get(
    "/{stream_id}/subscriptions",
    response_model=list[SubscriptionResponse],
    dependencies=[requires("read", "stream", id_param="stream_id")],
)
async def list_subscriptions(stream_id: UUID, service: StreamServiceDep):
    return [_subscription(row) for row in await service.list_subscriptions(stream_id)]


@router.post(
    "/{stream_id}/forwards",
    response_model=SubscriptionResponse,
    status_code=201,
    dependencies=[requires("edit", "stream", id_param="stream_id")],
)
async def create_forward(
    stream_id: UUID, data: ForwardCreate, user_context: UserContextDep, service: StreamServiceDep
):
    for output in data.output_stream_ids:
        await require_permission("edit", "stream", str(output), user_context.user_id)
    try:
        row = await service.create_forward(
            stream_id=stream_id,
            output_stream_ids=data.output_stream_ids,
            event_filter=data.event_filter,
        )
    except ForwardLoopError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except StreamNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except StreamManagedByPlatformError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return _subscription(row)


@router.delete(
    "/{stream_id}/subscriptions/{subscription_id}",
    status_code=204,
    dependencies=[requires("edit", "stream", id_param="stream_id")],
)
async def delete_forward(
    stream_id: UUID,
    subscription_id: UUID,
    user_context: UserContextDep,
    service: StreamServiceDep,
):
    """Remove a forward. The caller must be able to edit every output stream, as to create it.

    A trigger's subscription is refused with 409: it goes when the trigger is deleted.
    """
    try:
        forward = await service.get_forward(stream_id, subscription_id)
        for output in await service.existing_outputs(forward):
            await require_permission("edit", "stream", str(output), user_context.user_id)
        await service.delete_forward(stream_id, subscription_id)
    except SubscriptionNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except NotAForwardError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return Response(status_code=204)


_PROCESSOR_REFUSALS: tuple[tuple[type[Exception], int], ...] = (
    (SubscriptionNotFoundError, 404),
    (StreamNotFoundError, 404),
    (NotAProcessorError, 409),
    (StreamManagedByPlatformError, 409),
    (ProcessorCodeError, 400),
    (ProcessorLoopError, 400),
)
_PROCESSOR_ERRORS = tuple(error for error, _ in _PROCESSOR_REFUSALS)


def processor_refusal(error: Exception) -> HTTPException:
    """The answer to a refused processor change."""
    status = next(code for kind, code in _PROCESSOR_REFUSALS if isinstance(error, kind))
    return HTTPException(status_code=status, detail=str(error))


@router.post(
    "/{stream_id}/processors",
    response_model=SubscriptionResponse,
    status_code=201,
    dependencies=[requires("edit", "stream", id_param="stream_id")],
)
async def create_processor(
    stream_id: UUID, data: ProcessorCreate, user_context: UserContextDep, service: StreamServiceDep
):
    """Run code over every matching event of the stream; it writes into the output streams.

    The caller must be able to edit every output stream. The code runs in the
    sandbox, one call per event, and gets no secrets.
    """
    for output in data.output_stream_ids:
        await require_permission("edit", "stream", str(output), user_context.user_id)
    try:
        row = await service.create_processor(
            stream_id=stream_id,
            output_stream_ids=data.output_stream_ids,
            code=data.code,
            event_filter=data.event_filter,
        )
    except _PROCESSOR_ERRORS as error:
        raise processor_refusal(error) from error
    return _subscription(row)


@router.patch(
    "/{stream_id}/processors/{subscription_id}",
    response_model=SubscriptionResponse,
    dependencies=[requires("edit", "stream", id_param="stream_id")],
)
async def update_processor(
    stream_id: UUID,
    subscription_id: UUID,
    data: ProcessorUpdate,
    user_context: UserContextDep,
    service: StreamServiceDep,
):
    """Change a processor's code, outputs or filter; the next event runs the change.

    The caller must be able to edit every output stream it has and is given.
    """
    try:
        processor = await service.get_processor(stream_id, subscription_id)
        outputs = {*await service.existing_outputs(processor), *(data.output_stream_ids or [])}
        for output in sorted(outputs, key=str):
            await require_permission("edit", "stream", str(output), user_context.user_id)
        row = await service.update_processor(
            stream_id,
            subscription_id,
            code=data.code,
            output_stream_ids=data.output_stream_ids,
            event_filter=data.event_filter,
        )
    except _PROCESSOR_ERRORS as error:
        raise processor_refusal(error) from error
    return _subscription(row)


@router.delete(
    "/{stream_id}/processors/{subscription_id}",
    status_code=204,
    dependencies=[requires("edit", "stream", id_param="stream_id")],
)
async def delete_processor(
    stream_id: UUID,
    subscription_id: UUID,
    user_context: UserContextDep,
    service: StreamServiceDep,
):
    """Remove a processor; the events it wrote stay. The caller must be able to edit its outputs."""
    try:
        processor = await service.get_processor(stream_id, subscription_id)
        for output in await service.existing_outputs(processor):
            await require_permission("edit", "stream", str(output), user_context.user_id)
        await service.delete_processor(stream_id, subscription_id)
    except _PROCESSOR_ERRORS as error:
        raise processor_refusal(error) from error
    return Response(status_code=204)


@router.get(
    "/{stream_id}/events",
    response_model=StreamEventPage,
    dependencies=[requires("read", "stream", id_param="stream_id")],
)
async def list_events(
    stream_id: UUID,
    service: StreamServiceDep,
    reactions: ReactionsDep,
    after: int | None = Query(
        None, ge=0, le=MAX_BIGINT, description="Oldest first, after this sequence."
    ),
    before: int | None = Query(
        None, ge=1, le=MAX_BIGINT, description="Newest first, before this sequence."
    ),
    limit: int = Query(50, ge=1, le=200),
):
    if after is not None and before is not None:
        raise HTTPException(status_code=400, detail="Pass either after or before, not both")
    try:
        events = await service.list_events(stream_id, after=after, before=before, limit=limit)
    except StreamNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    full = len(events) == limit
    return StreamEventPage(
        events=await _events_with_outcomes(service, reactions, stream_id, events),
        next_after=events[-1].sequence if after is not None and full else None,
        next_before=events[-1].sequence if after is None and full else None,
    )


@router.get(
    "/{stream_id}/events/{sequence}",
    response_model=StreamEventDetailResponse,
    dependencies=[requires("read", "stream", id_param="stream_id")],
)
async def get_event(
    stream_id: UUID,
    user_context: UserContextDep,
    service: StreamServiceDep,
    reactions: ReactionsDep,
    # Sequences start at 1 and live in a BIGINT: anything outside is a 422, not
    # an overflow in the database.
    sequence: int = Path(ge=1, le=MAX_BIGINT),
):
    try:
        events = await service.list_events(stream_id, after=sequence - 1, before=None, limit=1)
    except StreamNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    if not events or events[0].sequence != sequence:
        raise HTTPException(status_code=404, detail=f"Event {sequence} not found in stream")
    return await _event_detail(service, reactions, user_context, events[0])


@router.get(
    "/{stream_id}/subscriptions/{subscription_id}/outcomes",
    response_model=list[OutcomeResponse],
    dependencies=[requires("read", "stream", id_param="stream_id")],
)
async def list_outcomes(
    stream_id: UUID,
    subscription_id: UUID,
    service: StreamServiceDep,
    reactions: ReactionsDep,
    limit: int = Query(50, ge=1, le=500),
):
    subscriptions = {row.id: row for row in await service.list_subscriptions(stream_id)}
    sub = subscriptions.get(subscription_id)
    if sub is None:
        raise HTTPException(status_code=404, detail="Subscription not found in stream")
    return [
        outcome_response(row, sub)
        for row in await reactions.list_for_subscription(subscription_id, limit)
    ]
