"""Streams: named event journals, their sources, subscriptions, events and outcomes."""

import logging
from typing import Annotated, Any
from uuid import UUID

from agentarea_api.api.deps.services import BaseSecretManagerDep, SecretCatalogServiceDep
from agentarea_common.auth.dependencies import UserContextDep
from agentarea_common.auth.permission import require_permission
from agentarea_common.auth.resource_visibility import readable_resource_ids
from agentarea_common.auth.route_authz import enforced_in_handler, requires, unrestricted
from agentarea_common.base import RepositoryFactoryDep
from agentarea_common.base.pagination import MAX_OFFSET
from agentarea_common.config import get_settings
from agentarea_common.utils.types import UtcDatetime
from agentarea_streams.application.stream_service import StreamService
from agentarea_streams.domain import (
    ForwardLoopError,
    JournaledEvent,
    NotAForwardError,
    SourceFedByTriggerError,
    StreamInUseError,
    StreamNameTakenError,
    StreamNotFoundError,
    StreamSourceNotFoundError,
    SubscriptionNotFoundError,
)
from agentarea_streams.schemas import ForwardCreate, StreamCreate, WebhookSourceCreate
from agentarea_triggers.channels.webhook_service import ChannelWebhookService
from agentarea_triggers.domain.source_types import STREAM_SOURCE_TYPES, StreamSourceType
from agentarea_triggers.webhook_verification import hmac_signature_scheme
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field

from ._icons import CHANNEL_ICON_NAMESPACE, build_icon_url
from ._stream_sources import (
    create_webhook_source,
    delete_stream_with_sources,
    release_webhook_source,
)
from ._trigger_creation import get_channel_webhook_service, public_webhook_url
from .triggers import WebhookSignatureScheme

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/streams", tags=["streams"])


async def get_stream_service(repository_factory: RepositoryFactoryDep) -> StreamService:
    return StreamService(repository_factory, get_settings().streams)


StreamServiceDep = Annotated[StreamService, Depends(get_stream_service)]


class StreamResponse(BaseModel):
    id: UUID
    name: str
    description: str
    kind: str
    retention_days: int
    created_by: str
    created_at: UtcDatetime

    model_config = {"from_attributes": True}


class StreamSourceResponse(BaseModel):
    id: UUID
    kind: str
    webhook_id: str | None
    webhook_type: str | None
    webhook_url: str | None = Field(
        description="Public URL senders post to; null for non-webhook sources."
    )
    allowed_methods: list[str] | None
    trigger_id: UUID | None = Field(
        default=None,
        description="The webhook trigger that owns this source; null for a source added directly.",
    )
    signature_scheme: WebhookSignatureScheme | None = Field(
        default=None,
        description="How a sender signs for a type verified by configurable HMAC; null otherwise.",
    )
    created_at: UtcDatetime


class WebhookSourceCreated(StreamSourceResponse):
    signing_secret: str | None = Field(
        default=None,
        description=(
            "Issued when the type's signing secret is optional and none was given; "
            "shown this once only."
        ),
    )


class StreamSourceTypeResponse(StreamSourceType):
    icon_url: str | None


ChannelWebhookServiceDep = Annotated[ChannelWebhookService, Depends(get_channel_webhook_service)]


def _signature_scheme(row: Any) -> WebhookSignatureScheme | None:
    if row.webhook_type is None:
        return None
    scheme = hmac_signature_scheme(row.webhook_type, row.validation_rules)
    if scheme is None:
        return None
    return WebhookSignatureScheme(
        header=scheme.header, algorithm=scheme.algorithm, prefix=scheme.prefix
    )


def source_response(row: Any) -> StreamSourceResponse:
    return StreamSourceResponse(
        id=row.id,
        kind=row.kind,
        webhook_id=row.webhook_id,
        webhook_type=row.webhook_type,
        webhook_url=public_webhook_url(row.webhook_id) if row.webhook_id else None,
        allowed_methods=row.allowed_methods,
        trigger_id=(
            row.credential_key
            if row.credential_key is not None and row.credential_key != row.id
            else None
        ),
        signature_scheme=_signature_scheme(row),
        created_at=row.created_at,
    )


def source_types() -> list[StreamSourceTypeResponse]:
    return [
        StreamSourceTypeResponse(
            **t.model_dump(), icon_url=build_icon_url(CHANNEL_ICON_NAMESPACE, t.icon)
        )
        for t in STREAM_SOURCE_TYPES
    ]


class SubscriptionResponse(BaseModel):
    id: UUID
    kind: str
    trigger_id: UUID | None
    filter: dict[str, Any]
    output_stream_ids: list[UUID]
    cursor_sequence: int
    status: str
    attempts: int
    last_error: str | None
    next_attempt_at: UtcDatetime | None
    created_at: UtcDatetime


class OutcomeResponse(BaseModel):
    subscription_id: UUID
    subscription_kind: str
    trigger_id: UUID | None
    event_sequence: int
    verdict: str = Field(description="reacted, skipped or error")
    reason: str | None
    score: float | None
    task_id: UUID | None
    derived_sequences: list[int]
    created_at: UtcDatetime


class StreamEventResponse(BaseModel):
    sequence: int
    event_id: UUID
    event_key: str
    kind: str
    source: str
    subject: str | None
    occurred_at: UtcDatetime
    received_at: UtcDatetime
    correlation_id: str | None
    causation_id: str | None
    depth: int
    data: dict[str, Any]
    outcomes: list[OutcomeResponse] = Field(
        description="One per subscription that took the event; empty means nobody listened."
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
        cursor_sequence=row.cursor_sequence,
        status=row.status,
        attempts=row.attempts,
        last_error=row.last_error,
        next_attempt_at=row.next_attempt_at,
        created_at=row.created_at,
    )


async def _events_with_outcomes(
    service: StreamService, stream_id: UUID, events: list[JournaledEvent]
) -> list[StreamEventResponse]:
    subscriptions = {row.id: row for row in await service.list_subscriptions(stream_id)}
    outcomes = await service.outcomes_for(stream_id, [e.sequence for e in events])
    by_event: dict[int, list[OutcomeResponse]] = {}
    for outcome in outcomes:
        sub = subscriptions.get(outcome.subscription_id)
        by_event.setdefault(outcome.event_sequence, []).append(
            OutcomeResponse(
                subscription_id=outcome.subscription_id,
                subscription_kind=sub.kind if sub else "deleted",
                trigger_id=sub.trigger_id if sub else None,
                event_sequence=outcome.event_sequence,
                verdict=outcome.verdict,
                reason=outcome.reason,
                score=outcome.score,
                task_id=outcome.task_id,
                derived_sequences=list(outcome.derived_sequences or []),
                created_at=outcome.created_at,
            )
        )
    return [
        StreamEventResponse(
            sequence=e.sequence,
            event_id=e.id,
            event_key=e.event_key,
            kind=e.type,
            source=e.source,
            subject=e.subject,
            occurred_at=e.time,
            received_at=e.received_at,
            correlation_id=e.correlation_id,
            causation_id=e.causation_id,
            depth=e.depth,
            data=e.data,
            outcomes=by_event.get(e.sequence, []),
        )
        for e in events
    ]


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
        return await service.create_stream(
            name=data.name, description=data.description, retention_days=data.retention_days
        )
    except StreamNameTakenError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get(
    "/source-types",
    response_model=list[StreamSourceTypeResponse],
    dependencies=[unrestricted("platform catalogue data, identical for every workspace")],
)
async def list_source_types():
    """Webhook types a source can be, with the credentials and settings each needs."""
    return source_types()


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
    webhook_service: ChannelWebhookServiceDep,
):
    """Delete a stream with its events, sources and subscriptions.

    Refused with 409 while a live webhook trigger's source feeds the stream,
    while a trigger subscribes to it (delete the trigger first), or while a
    forward of any stream writes into it (remove that forward first).
    """
    try:
        await delete_stream_with_sources(
            stream_id,
            service=service,
            secret_manager=secret_manager,
            secret_catalog=secret_catalog,
            webhook_service=webhook_service,
        )
    except StreamNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except (SourceFedByTriggerError, StreamInUseError) as error:
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
    response_model=WebhookSourceCreated,
    status_code=201,
    dependencies=[requires("edit", "stream", id_param="stream_id")],
)
async def create_source(
    stream_id: UUID,
    data: WebhookSourceCreate,
    service: StreamServiceDep,
    secret_manager: BaseSecretManagerDep,
    secret_catalog: SecretCatalogServiceDep,
    webhook_service: ChannelWebhookServiceDep,
):
    """Add a webhook source to the stream, with no trigger.

    Credentials are write-only and held by reference; the response carries the
    public URL to give the sender.
    """
    try:
        row, issued = await create_webhook_source(
            stream_id,
            data,
            service=service,
            secret_manager=secret_manager,
            secret_catalog=secret_catalog,
            webhook_service=webhook_service,
        )
    except StreamNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return WebhookSourceCreated(**source_response(row).model_dump(), signing_secret=issued)


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
    webhook_service: ChannelWebhookServiceDep,
):
    """Remove a webhook source; one a live trigger owns is refused with 409."""
    try:
        source = await service.delete_source(stream_id, source_id)
    except StreamSourceNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except SourceFedByTriggerError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    await release_webhook_source(
        source,
        secret_manager=secret_manager,
        secret_catalog=secret_catalog,
        webhook_service=webhook_service,
    )
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


@router.get(
    "/{stream_id}/events",
    response_model=StreamEventPage,
    dependencies=[requires("read", "stream", id_param="stream_id")],
)
async def list_events(
    stream_id: UUID,
    service: StreamServiceDep,
    after: int | None = Query(None, ge=0, description="Oldest first, after this sequence."),
    before: int | None = Query(None, ge=1, description="Newest first, before this sequence."),
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
        events=await _events_with_outcomes(service, stream_id, events),
        next_after=events[-1].sequence if after is not None and full else None,
        next_before=events[-1].sequence if after is None and full else None,
    )


@router.get(
    "/{stream_id}/events/{sequence}",
    response_model=StreamEventResponse,
    dependencies=[requires("read", "stream", id_param="stream_id")],
)
async def get_event(stream_id: UUID, sequence: int, service: StreamServiceDep):
    events = await service.list_events(stream_id, after=sequence - 1, before=None, limit=1)
    if not events or events[0].sequence != sequence:
        raise HTTPException(status_code=404, detail=f"Event {sequence} not found in stream")
    (response,) = await _events_with_outcomes(service, stream_id, events)
    return response


@router.get(
    "/{stream_id}/subscriptions/{subscription_id}/outcomes",
    response_model=list[OutcomeResponse],
    dependencies=[requires("read", "stream", id_param="stream_id")],
)
async def list_outcomes(
    stream_id: UUID,
    subscription_id: UUID,
    service: StreamServiceDep,
    limit: int = Query(50, ge=1, le=500),
):
    subscriptions = {row.id: row for row in await service.list_subscriptions(stream_id)}
    sub = subscriptions.get(subscription_id)
    if sub is None:
        raise HTTPException(status_code=404, detail="Subscription not found in stream")
    return [
        OutcomeResponse(
            subscription_id=row.subscription_id,
            subscription_kind=sub.kind,
            trigger_id=sub.trigger_id,
            event_sequence=row.event_sequence,
            verdict=row.verdict,
            reason=row.reason,
            score=row.score,
            task_id=row.task_id,
            derived_sequences=list(row.derived_sequences or []),
            created_at=row.created_at,
        )
        for row in await service.outcomes_of_subscription(subscription_id, limit)
    ]
