"""StreamsToolset — event streams: what arrived, who listened, what they decided.

The source of truth for create/create_forward is ``StreamCreate``/``ForwardCreate``
in ``agentarea_streams.schemas``; ``libs/agents/tests/test_mcp_rest_parity.py``
enforces parity with the REST routes in ``api/v1/streams.py``.
"""

import builtins
import json
from typing import Any
from uuid import UUID

from agentarea_agents_sdk.tools.decorator_tool import Toolset, tool_method
from agentarea_agents_sdk.tools.tool_authz import enforced_in_handler, requires, unrestricted
from agentarea_agents_sdk.tools.tool_definition import toolset
from agentarea_common.auth.permission import require_permission
from agentarea_common.auth.resource_visibility import readable_resource_ids
from agentarea_common.base.pagination import MAX_OFFSET
from agentarea_common.config import get_settings
from agentarea_streams.application.stream_service import StreamService
from agentarea_streams.domain import EventFilter, StreamError
from agentarea_streams.schemas import ForwardCreate, StreamCreate
from fastapi import HTTPException

from ..api.v1._trigger_creation import public_webhook_url
from ..api.v1.streams import (
    StreamEventPage,
    StreamResponse,
    StreamSourceResponse,
    _events_with_outcomes,
    _subscription,
)
from .base import platform_context, platform_read_context


def _service(repo_factory: Any) -> StreamService:
    return StreamService(repo_factory, get_settings().streams)


def _out_of_range(name: str, value: int, low: int, high: int | None = None) -> str | None:
    """The REST routes' Query(ge=, le=) bounds; MCP arguments are not validated before the call."""
    if value >= low and (high is None or value <= high):
        return None
    bounds = f"between {low} and {high}" if high is not None else f"at least {low}"
    return json.dumps({"error": f"{name} must be {bounds}, got {value}"})


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

    @tool_method(effect="read")
    @enforced_in_handler("narrowed to the rows the graph says this caller may read")
    async def list(self, limit: int = 100, offset: int = 0) -> str:
        """List the workspace's streams. limit is 1-1000."""
        if refused := _out_of_range("limit", limit, 1, 1000) or _out_of_range(
            "offset", offset, 0, MAX_OFFSET
        ):
            return refused
        async with platform_read_context() as (_s, user_ctx, repo_factory, _b, _sec):
            rows = await _service(repo_factory).list_streams(
                limit=limit, offset=offset, ids=await readable_resource_ids(user_ctx.user_id)
            )
            return json.dumps(
                [StreamResponse.model_validate(r).model_dump(mode="json") for r in rows]
            )

    @tool_method(effect="read")
    @requires("read", "stream", id_param="stream_id")
    async def get(self, stream_id: str) -> str:
        """Get a stream."""
        async with platform_read_context() as (_s, _u, repo_factory, _b, _sec):
            try:
                row = await _service(repo_factory).get_stream(UUID(stream_id))
            except StreamError as error:
                return json.dumps({"error": str(error)})
            return StreamResponse.model_validate(row).model_dump_json()

    @tool_method(effect="write")
    @unrestricted("any member may create a stream, as POST /v1/streams allows")
    async def create(
        self, name: str, description: str = "", retention_days: int | None = None
    ) -> str:
        """Create a stream. retention_days defaults to the deployment's retention."""
        payload = StreamCreate(name=name, description=description, retention_days=retention_days)
        async with platform_context() as (_s, _u, repo_factory, _b, _sec):
            row = await _service(repo_factory).create_stream(
                name=payload.name,
                description=payload.description,
                retention_days=payload.retention_days,
            )
            return StreamResponse.model_validate(row).model_dump_json()

    @tool_method(effect="destructive")
    @requires("delete", "stream", id_param="stream_id")
    async def delete(self, stream_id: str) -> str:
        """Delete a stream and its events, sources and subscriptions."""
        async with platform_context() as (_s, _u, repo_factory, _b, _sec):
            try:
                await _service(repo_factory).delete_stream(UUID(stream_id))
            except StreamError as error:
                return json.dumps({"error": str(error)})
            return json.dumps({"deleted": True})

    @tool_method(effect="read")
    @requires("read", "stream", id_param="stream_id")
    async def list_sources(self, stream_id: str) -> str:
        """List where a stream's events come from, with the public webhook URL."""
        async with platform_read_context() as (_s, _u, repo_factory, _b, _sec):
            rows = await _service(repo_factory).list_sources(UUID(stream_id))
            return json.dumps(
                [
                    StreamSourceResponse(
                        id=r.id,
                        kind=r.kind,
                        webhook_id=r.webhook_id,
                        webhook_type=r.webhook_type,
                        webhook_url=public_webhook_url(r.webhook_id) if r.webhook_id else None,
                        allowed_methods=r.allowed_methods,
                        created_at=r.created_at,
                    ).model_dump(mode="json")
                    for r in rows
                ]
            )

    @tool_method(effect="read")
    @requires("read", "stream", id_param="stream_id")
    async def list_subscriptions(self, stream_id: str) -> str:
        """List the triggers and forwards that receive a stream's events."""
        async with platform_read_context() as (_s, _u, repo_factory, _b, _sec):
            rows = await _service(repo_factory).list_subscriptions(UUID(stream_id))
            return json.dumps([_subscription(r).model_dump(mode="json") for r in rows])

    @tool_method(effect="write")
    @requires("edit", "stream", id_param="stream_id")
    async def create_forward(
        self,
        stream_id: str,
        output_stream_ids: builtins.list[str],
        event_filter: dict[str, Any] | None = None,
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
                return json.dumps({"error": exc.detail})
            try:
                row = await _service(repo_factory).create_forward(
                    stream_id=UUID(stream_id),
                    output_stream_ids=payload.output_stream_ids,
                    event_filter=payload.event_filter,
                )
            except StreamError as error:
                return json.dumps({"error": str(error)})
            return _subscription(row).model_dump_json()

    @tool_method(effect="read")
    @requires("read", "stream", id_param="stream_id")
    async def list_events(self, stream_id: str, after: int = 0, limit: int = 50) -> str:
        """Events after a sequence, oldest first, each with every subscription's outcome.

        Pass the returned ``next_after`` as ``after`` for the next page; null at the end.
        limit is 1-200.
        """
        if refused := _out_of_range("limit", limit, 1, 200) or _out_of_range("after", after, 0):
            return refused
        async with platform_read_context() as (_s, _u, repo_factory, _b, _sec):
            service = _service(repo_factory)
            try:
                events = await service.list_events(
                    UUID(stream_id), after=after, before=None, limit=limit
                )
            except StreamError as error:
                return json.dumps({"error": str(error)})
            return StreamEventPage(
                events=await _events_with_outcomes(service, UUID(stream_id), events),
                next_after=events[-1].sequence if len(events) == limit else None,
            ).model_dump_json()
