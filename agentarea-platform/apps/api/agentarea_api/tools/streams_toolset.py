"""StreamsToolset — event streams: what arrived, who listened, what they decided.

The source of truth for create/create_forward is ``StreamCreate``/``ForwardCreate``
in ``agentarea_streams.schemas``; ``libs/agents/tests/test_mcp_rest_parity.py``
enforces parity with the REST routes in ``api/v1/streams.py``.
"""

import builtins
import json
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from agentarea_agents_sdk.tools.base_tool import ToolError
from agentarea_agents_sdk.tools.decorator_tool import Toolset, tool_method
from agentarea_agents_sdk.tools.tool_authz import enforced_in_handler, requires, unrestricted
from agentarea_agents_sdk.tools.tool_definition import toolset
from agentarea_common.auth.permission import require_permission
from agentarea_common.auth.resource_visibility import readable_resource_ids
from agentarea_common.base.pagination import MAX_OFFSET
from agentarea_common.config import get_settings
from agentarea_secrets.catalog_service import SecretCatalogService
from agentarea_streams.application.stream_service import StreamService
from agentarea_streams.domain import EventFilter, StreamError
from agentarea_streams.domain.enums import SourceKind
from agentarea_streams.domain.feed import FeedFilter
from agentarea_streams.domain.processing import ProcessingStatus
from agentarea_streams.domain.source_types import EventOverrides
from agentarea_streams.schemas import (
    ForwardCreate,
    ProcessorCreate,
    ProcessorUpdate,
    SourceCreate,
    StreamCreate,
)
from agentarea_triggers.infrastructure.reactions import ReactionRepository
from fastapi import HTTPException
from pydantic import BaseModel, Field, ValidationError

from ..api.v1._stream_sources import (
    create_source,
    delete_stream_with_sources,
    release_source,
)
from ..api.v1.streams import (
    SourceCreated,
    SourceTypeResponse,
    StreamEventPage,
    StreamResponse,
    StreamSourceResponse,
    SubscriptionResponse,
    _events_with_outcomes,
    _subscription,
    source_response,
    source_types,
    workspace_events,
)
from .base import platform_context, platform_read_context

StreamId = Annotated[
    str, Field(description="Stream id (UUID), from `streams_list` or `streams_create`.")
]


class StreamDeletedOutput(BaseModel):
    deleted: bool = Field(description="True once the stream and everything it held are gone.")


class SourceDeletedOutput(BaseModel):
    deleted: bool = Field(description="True once the source is removed.")


class ForwardDeletedOutput(BaseModel):
    deleted: bool = Field(description="True once the forward is removed.")


class ProcessorDeletedOutput(BaseModel):
    deleted: bool = Field(description="True once the processor is removed.")


SubscriptionId = Annotated[
    str, Field(description="Processor's subscription id (UUID), from `streams_list_subscriptions`.")
]


def _service(repo_factory: Any) -> StreamService:
    return StreamService(repo_factory, get_settings().streams)


def _secret_ports(session: Any, user_ctx: Any, secret_manager: Any) -> dict[str, Any]:
    return {
        "secret_manager": secret_manager,
        "secret_catalog": SecretCatalogService(session, user_ctx, secret_manager),
    }


def _check_range(name: str, value: int, low: int, high: int | None = None) -> None:
    """The REST routes' Query(ge=, le=) bounds; MCP arguments are not validated before the call."""
    if value >= low and (high is None or value <= high):
        return
    bounds = f"between {low} and {high}" if high is not None else f"at least {low}"
    raise ToolError(f"{name} must be {bounds}, got {value}")


@toolset(
    namespace="agentarea/streams",
    display_name="Event Streams",
    description=(
        "Create event streams and forwards between them; read what arrived, who listened "
        "and what they decided."
    ),
    category="platform",
    plane="build",
)
class StreamsToolset(Toolset):
    """Streams: list, get, create, delete; sources, subscriptions, forwards, events."""

    open_world = False

    @tool_method(display_name="List streams", effect="read", output=builtins.list[StreamResponse])
    @enforced_in_handler("narrowed to the rows the graph says this caller may read")
    async def list(
        self,
        limit: Annotated[int, Field(description="Page size, 1-1000.")] = 100,
        offset: Annotated[int, Field(description="Streams to skip before the page starts.")] = 0,
    ) -> str:
        """List the workspace's streams. limit is 1-1000."""
        _check_range("limit", limit, 1, 1000)
        _check_range("offset", offset, 0, MAX_OFFSET)
        async with platform_read_context() as (_s, user_ctx, repo_factory, _b, _sec):
            rows = await _service(repo_factory).list_streams(
                limit=limit, offset=offset, ids=await readable_resource_ids(user_ctx.user_id)
            )
            return json.dumps(
                [StreamResponse.model_validate(r).model_dump(mode="json") for r in rows]
            )

    @tool_method(display_name="Get stream", effect="read", output=StreamResponse)
    @requires("read", "stream", id_param="stream_id")
    async def get(self, stream_id: StreamId) -> str:
        """Get a stream."""
        async with platform_read_context() as (_s, _u, repo_factory, _b, _sec):
            try:
                row = await _service(repo_factory).get_stream(UUID(stream_id))
            except StreamError as error:
                raise ToolError(str(error)) from error
            return StreamResponse.model_validate(row).model_dump_json()

    @tool_method(display_name="Create stream", effect="write", output=StreamResponse)
    @unrestricted("any member may create a stream, as POST /v1/streams allows")
    async def create(
        self,
        name: Annotated[
            str, Field(description="Stream name, unique in the workspace; 1-255 characters.")
        ],
        description: Annotated[
            str, Field(description="What the stream carries; up to 1000 characters.")
        ] = "",
    ) -> str:
        """Create a stream. Its events are kept for the deployment's retention."""
        payload = StreamCreate(name=name, description=description)
        async with platform_context() as (_s, _u, repo_factory, _b, _sec):
            try:
                row = await _service(repo_factory).create_stream(
                    name=payload.name, description=payload.description
                )
            except StreamError as error:
                raise ToolError(str(error)) from error
            return StreamResponse.model_validate(row).model_dump_json()

    @tool_method(
        display_name="Delete stream",
        effect="destructive",
        idempotent=True,
        open_world=True,
        output=StreamDeletedOutput,
    )
    @requires("delete", "stream", id_param="stream_id")
    async def delete(self, stream_id: StreamId) -> str:
        """Delete a stream and its events, sources and subscriptions.

        Refused while a trigger subscribes to it (delete the trigger first), or while
        a forward of any stream writes into it (remove that forward with
        ``streams_delete_forward`` first).
        """
        async with platform_context() as (session, user_ctx, repo_factory, _b, secret_manager):
            try:
                await delete_stream_with_sources(
                    UUID(stream_id),
                    service=_service(repo_factory),
                    **_secret_ports(session, user_ctx, secret_manager),
                )
            except StreamError as error:
                raise ToolError(str(error)) from error
            return json.dumps({"deleted": True})

    @tool_method(
        display_name="List stream source types",
        effect="read",
        output=builtins.list[SourceTypeResponse],
    )
    @unrestricted("platform catalogue data, as GET /v1/streams/source-types serves it")
    async def list_source_types(self) -> str:
        """Source types of the catalog, with the credentials and settings each needs."""
        async with platform_read_context() as (_s, _u, repo_factory, _b, _sec):
            types = await source_types(_service(repo_factory))
            return json.dumps([t.model_dump(mode="json") for t in types])

    @tool_method(
        display_name="List stream sources",
        effect="read",
        output=builtins.list[StreamSourceResponse],
    )
    @requires("read", "stream", id_param="stream_id")
    async def list_sources(self, stream_id: StreamId) -> str:
        """List where a stream's events come from, with the public webhook URL."""
        async with platform_read_context() as (_s, _u, repo_factory, _b, _sec):
            rows = await _service(repo_factory).list_sources(UUID(stream_id))
            return json.dumps([source_response(r).model_dump(mode="json") for r in rows])

    @tool_method(
        display_name="Add source to stream",
        effect="write",
        open_world=True,
        output=SourceCreated,
    )
    @requires("edit", "stream", id_param="stream_id")
    async def create_source(
        self,
        stream_id: StreamId,
        source_type: Annotated[
            str,
            Field(description="A `slug` from `streams_list_source_types`."),
        ],
        kind: Annotated[
            SourceKind,
            Field(
                description=(
                    "webhook: the provider posts to the returned URL; poll: the platform "
                    "fetches. Must be in the type's `delivery`."
                )
            ),
        ] = SourceKind.WEBHOOK,
        credentials: Annotated[
            dict[str, Any] | None,
            Field(
                description=(
                    "The type's `credentials` fields by key, each a string value or "
                    '{"secret_id": "<uuid>"} of a workspace secret from `secrets_list`. '
                    "Write-only."
                )
            ),
        ] = None,
        config: Annotated[
            dict[str, str] | None,
            Field(description="The type's `config` fields by key, as strings (e.g. shop_id)."),
        ] = None,
        event_templates: Annotated[
            dict[str, Any] | None,
            Field(
                description=(
                    'This source\'s own {"kind", "key", "session_key"} templates, e.g. '
                    '{"key": "{body:id}"}; for a generic webhook, the key dedups retries.'
                )
            ),
        ] = None,
    ) -> str:
        """Add a webhook or poll source to a stream; a webhook source returns its public URL.

        Credentials are stored by reference and never returned; ones the type
        issues and you left out come back once in ``issued``.
        """
        try:
            payload = SourceCreate(
                source_type=source_type,
                kind=kind,
                credentials=credentials or {},
                config=config or {},
                event_templates=(
                    EventOverrides.model_validate(event_templates) if event_templates else None
                ),
            )
        except ValidationError as error:
            raise ToolError(str(error)) from error
        async with platform_context() as (session, user_ctx, repo_factory, _b, secret_manager):
            try:
                row, issued = await create_source(
                    UUID(stream_id),
                    payload,
                    service=_service(repo_factory),
                    **_secret_ports(session, user_ctx, secret_manager),
                )
            except (HTTPException, StreamError) as error:
                # A refusal after the row was flushed must not commit with the scope.
                await session.rollback()
                detail = error.detail if isinstance(error, HTTPException) else str(error)
                raise ToolError(detail) from error
            return SourceCreated(
                **source_response(row).model_dump(), issued=issued
            ).model_dump_json()

    @tool_method(
        display_name="Remove stream source",
        effect="destructive",
        idempotent=True,
        open_world=True,
        output=SourceDeletedOutput,
    )
    @requires("edit", "stream", id_param="stream_id")
    async def delete_source(
        self,
        stream_id: StreamId,
        source_id: Annotated[
            str, Field(description="Source id (UUID), from `streams_list_sources`.")
        ],
    ) -> str:
        """Remove a source and its credentials; its events stay."""
        async with platform_context() as (session, user_ctx, repo_factory, _b, secret_manager):
            try:
                source = await _service(repo_factory).delete_source(
                    UUID(stream_id), UUID(source_id)
                )
                await release_source(source, **_secret_ports(session, user_ctx, secret_manager))
            except StreamError as error:
                raise ToolError(str(error)) from error
            return json.dumps({"deleted": True})

    @tool_method(
        display_name="List stream subscriptions",
        effect="read",
        output=builtins.list[SubscriptionResponse],
    )
    @requires("read", "stream", id_param="stream_id")
    async def list_subscriptions(self, stream_id: StreamId) -> str:
        """List the triggers, forwards and processors that receive a stream's events."""
        async with platform_read_context() as (_s, _u, repo_factory, _b, _sec):
            rows = await _service(repo_factory).list_subscriptions(UUID(stream_id))
            return json.dumps([_subscription(r).model_dump(mode="json") for r in rows])

    @tool_method(display_name="Create stream forward", effect="write", output=SubscriptionResponse)
    @requires("edit", "stream", id_param="stream_id")
    async def create_forward(
        self,
        stream_id: Annotated[
            str,
            Field(
                description="Id (UUID) of the stream whose events are copied, from `streams_list`."
            ),
        ],
        output_stream_ids: Annotated[
            builtins.list[str],
            Field(
                description=(
                    "Ids (UUID) of the streams events are copied into, from `streams_list`; "
                    "at least one, never the input stream."
                )
            ),
        ],
        event_filter: Annotated[
            dict[str, Any] | None,
            Field(
                description=(
                    'Which events are copied: {"kinds": [<event kind>, ...], "fields": '
                    "{<dotted path in the event data>: <value>}}; null or {} copies all."
                )
            ),
        ] = None,
    ) -> str:
        """Copy every matching event of this stream into the output streams.

        ``event_filter`` picks events: {"kinds": ["push"], "fields": {"raw_data.action":
        "opened"}}; empty copies every event. The caller must be able to edit every
        output stream.
        """
        async with platform_context() as (_s, user_ctx, repo_factory, _b, _sec):
            payload = ForwardCreate(
                output_stream_ids=[UUID(s) for s in output_stream_ids],
                event_filter=EventFilter.model_validate(event_filter or {}),
            )
            try:
                for output in payload.output_stream_ids:
                    await require_permission("edit", "stream", str(output), user_ctx.user_id)
            except HTTPException as exc:
                raise ToolError(exc.detail) from exc
            try:
                row = await _service(repo_factory).create_forward(
                    stream_id=UUID(stream_id),
                    output_stream_ids=payload.output_stream_ids,
                    event_filter=payload.event_filter,
                )
            except StreamError as error:
                raise ToolError(str(error)) from error
            return _subscription(row).model_dump_json()

    @tool_method(
        display_name="Delete stream forward",
        effect="destructive",
        idempotent=True,
        output=ForwardDeletedOutput,
    )
    @requires("edit", "stream", id_param="stream_id")
    async def delete_forward(
        self,
        stream_id: StreamId,
        subscription_id: Annotated[
            str,
            Field(
                description="Forward's subscription id (UUID), from `streams_list_subscriptions`."
            ),
        ],
    ) -> str:
        """Remove a forward of this stream; ``subscription_id`` is from ``streams_list_subscriptions``.

        The caller must be able to edit every output stream, as to create it. A
        trigger's subscription is refused: it goes when the trigger is deleted.
        """
        async with platform_context() as (_s, user_ctx, repo_factory, _b, _sec):
            service = _service(repo_factory)
            try:
                forward = await service.get_forward(UUID(stream_id), UUID(subscription_id))
                for output in await service.existing_outputs(forward):
                    await require_permission("edit", "stream", str(output), user_ctx.user_id)
                await service.delete_forward(UUID(stream_id), UUID(subscription_id))
            except HTTPException as exc:
                raise ToolError(exc.detail) from exc
            except StreamError as error:
                raise ToolError(str(error)) from error
            return json.dumps({"deleted": True})

    @tool_method(
        display_name="Create stream processor", effect="write", output=SubscriptionResponse
    )
    @requires("edit", "stream", id_param="stream_id")
    async def create_processor(
        self,
        stream_id: Annotated[
            str,
            Field(description="Id (UUID) of the stream whose events the code reads."),
        ],
        output_stream_ids: Annotated[
            builtins.list[str],
            Field(
                description=(
                    "Ids (UUID) of the streams the code may write to, from `streams_list`; "
                    "at least one, never the input stream."
                )
            ),
        ],
        code: Annotated[str, Field(description=ProcessorCreate.model_fields["code"].description)],
        event_filter: Annotated[
            dict[str, Any] | None,
            Field(
                description=(
                    'Which events the code runs on: {"kinds": [...], "fields": {...}}; '
                    "null runs it on every event."
                )
            ),
        ] = None,
    ) -> str:
        """Run Python you write over every event of this stream; it writes new events.

        ``code`` defines ``def process(event: dict) -> list[dict] | None``. ``event``
        has ``id, kind, key, data, source_type, session_key, sender, subject, time,
        correlation_id, depth, stream_id, attachments``; ``data`` is what the source
        delivered (a webhook's JSON body is ``data["body"]``), so read a recent event
        with ``streams_list_events`` first. Return a list of
        ``{"stream": <output id or name>, "kind": str, "data": dict, "key": str?}``,
        or None to drop the event; a single dict is an error. It runs in the sandbox, one call per event, with
        a 10 s limit and no secrets; an exception is recorded as the event's error.
        Example: events of kind ``order.*`` with amount over 100 into ``big-orders``::

            def process(event):
                order = event["data"]["body"]
                if event["kind"].startswith("order.") and order.get("amount", 0) > 100:
                    return [{"stream": "big-orders", "kind": event["kind"], "data": order}]
                return None

        The caller must be able to edit every output stream.
        """
        try:
            payload = ProcessorCreate(
                output_stream_ids=[UUID(s) for s in output_stream_ids],
                code=code,
                event_filter=EventFilter.model_validate(event_filter or {}),
            )
        except (ValidationError, ValueError) as error:
            raise ToolError(str(error)) from error
        async with platform_context() as (_s, user_ctx, repo_factory, _b, _sec):
            try:
                for output in payload.output_stream_ids:
                    await require_permission("edit", "stream", str(output), user_ctx.user_id)
                row = await _service(repo_factory).create_processor(
                    stream_id=UUID(stream_id),
                    output_stream_ids=payload.output_stream_ids,
                    code=payload.code,
                    event_filter=payload.event_filter,
                )
            except HTTPException as exc:
                raise ToolError(exc.detail) from exc
            except StreamError as error:
                raise ToolError(str(error)) from error
            return _subscription(row).model_dump_json()

    @tool_method(
        display_name="Update stream processor", effect="write", output=SubscriptionResponse
    )
    @requires("edit", "stream", id_param="stream_id")
    async def update_processor(
        self,
        stream_id: StreamId,
        subscription_id: SubscriptionId,
        code: Annotated[
            str | None, Field(description="New code, as for `streams_create_processor`.")
        ] = None,
        output_stream_ids: Annotated[
            builtins.list[str] | None,
            Field(description="New output stream ids (UUID); null keeps them."),
        ] = None,
        event_filter: Annotated[
            dict[str, Any] | None, Field(description="New event filter; null keeps it.")
        ] = None,
    ) -> str:
        """Change a processor's code, outputs or filter; the next event runs the change.

        The caller must be able to edit every output stream it has and is given.
        """
        try:
            payload = ProcessorUpdate(
                code=code,
                output_stream_ids=(
                    [UUID(s) for s in output_stream_ids] if output_stream_ids is not None else None
                ),
                event_filter=(
                    EventFilter.model_validate(event_filter) if event_filter is not None else None
                ),
            )
        except (ValidationError, ValueError) as error:
            raise ToolError(str(error)) from error
        async with platform_context() as (_s, user_ctx, repo_factory, _b, _sec):
            service = _service(repo_factory)
            try:
                processor = await service.get_processor(UUID(stream_id), UUID(subscription_id))
                outputs = {
                    *await service.existing_outputs(processor),
                    *(payload.output_stream_ids or []),
                }
                for output in sorted(outputs, key=str):
                    await require_permission("edit", "stream", str(output), user_ctx.user_id)
                row = await service.update_processor(
                    UUID(stream_id),
                    UUID(subscription_id),
                    code=payload.code,
                    output_stream_ids=payload.output_stream_ids,
                    event_filter=payload.event_filter,
                )
            except HTTPException as exc:
                raise ToolError(exc.detail) from exc
            except StreamError as error:
                raise ToolError(str(error)) from error
            return _subscription(row).model_dump_json()

    @tool_method(
        display_name="Delete stream processor",
        effect="destructive",
        idempotent=True,
        output=ProcessorDeletedOutput,
    )
    @requires("edit", "stream", id_param="stream_id")
    async def delete_processor(self, stream_id: StreamId, subscription_id: SubscriptionId) -> str:
        """Remove a processor of this stream; the events it wrote stay.

        The caller must be able to edit every output stream, as to create it.
        """
        async with platform_context() as (_s, user_ctx, repo_factory, _b, _sec):
            service = _service(repo_factory)
            try:
                processor = await service.get_processor(UUID(stream_id), UUID(subscription_id))
                for output in await service.existing_outputs(processor):
                    await require_permission("edit", "stream", str(output), user_ctx.user_id)
                await service.delete_processor(UUID(stream_id), UUID(subscription_id))
            except HTTPException as exc:
                raise ToolError(exc.detail) from exc
            except StreamError as error:
                raise ToolError(str(error)) from error
            return json.dumps({"deleted": True})

    @tool_method(display_name="List stream events", effect="read", output=StreamEventPage)
    @enforced_in_handler(
        "read on the stream named; without one, narrowed to the streams the caller may read"
    )
    async def list_events(
        self,
        stream_id: Annotated[
            str | None,
            Field(
                description="Stream id (UUID), from `streams_list`. Leave it out for every "
                "stream of the workspace you may read."
            ),
        ] = None,
        after: Annotated[
            int,
            Field(
                description="With stream_id and no other filter: events with a sequence above "
                "this, oldest first; 0 starts at the oldest, then pass `next_after`."
            ),
        ] = 0,
        before: Annotated[
            int | None,
            Field(description="Workspace feed: events older than this sequence (`next_before`)."),
        ] = None,
        source_type: Annotated[
            str | None, Field(description="Source type slug, from `streams_list_source_types`.")
        ] = None,
        kind: Annotated[
            str | None,
            Field(description="Event kind, or a prefix ending in `.*` (e.g. `order.*`)."),
        ] = None,
        sender: Annotated[str | None, Field(description="Who sent it.")] = None,
        session_key: Annotated[
            str | None, Field(description="Every event of one session (`session_key`).")
        ] = None,
        result: Annotated[
            ProcessingStatus | None,
            Field(
                description="What the platform did with it: queued, processing, handled, "
                "error, no_handlers or skipped."
            ),
        ] = None,
        since: Annotated[datetime | None, Field(description="Received at or after.")] = None,
        until: Annotated[datetime | None, Field(description="Received before.")] = None,
        limit: Annotated[int, Field(description="Page size, 1-200.")] = 50,
    ) -> str:
        """Events, each with every subscription's outcome.

        With ``stream_id`` alone: that stream's events after a sequence, oldest
        first; pass ``next_after`` as ``after`` for the next page. Otherwise the
        workspace feed: every event of the streams you may read (``stream_id``
        narrows it), newest first, filtered, each with ``processing``; pass
        ``next_before`` as ``before`` for older events. limit is 1-200.
        """
        _check_range("limit", limit, 1, 200)
        _check_range("after", after, 0)
        filters = FeedFilter(
            stream_id=UUID(stream_id) if stream_id else None,
            source_type=source_type,
            kind=kind,
            sender=sender,
            session_key=session_key,
            result=result,
            since=since,
            until=until,
        )
        async with platform_read_context() as (_s, user_ctx, repo_factory, _b, _sec):
            service = _service(repo_factory)
            reactions = repo_factory.create_repository(ReactionRepository)
            stream_only = filters == FeedFilter(stream_id=filters.stream_id) and before is None
            if filters.stream_id is None or not stream_only:
                if before is not None:
                    _check_range("before", before, 1)
                page = await workspace_events(
                    service, reactions, user_ctx, filters, before=before, limit=limit
                )
                return page.model_dump_json()
            try:
                await require_permission("read", "stream", str(filters.stream_id), user_ctx.user_id)
                events = await service.list_events(
                    filters.stream_id, after=after, before=None, limit=limit
                )
            except HTTPException as exc:
                raise ToolError(exc.detail) from exc
            except StreamError as error:
                raise ToolError(str(error)) from error
            return StreamEventPage(
                events=await _events_with_outcomes(service, reactions, filters.stream_id, events),
                next_after=events[-1].sequence if len(events) == limit else None,
            ).model_dump_json()
