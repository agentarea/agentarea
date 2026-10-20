"""Sources a member adds to a stream: a webhook or poll source of a catalog entry.

A source holds no secret. Its credentials live in the secret store under
``channel_cred:{slug}:{source_id}``: a typed value is kept there, a picked
workspace secret only as ``{"secret_name": ...}`` and read at use. Registering
a webhook with the provider (Telegram's setWebhook) is the Go reconciler's job.
Shared by the REST routes and the streams toolset.
"""

import base64
import binascii
import json
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from agentarea_common.auth.permission import require_permission
from agentarea_common.config.app import get_app_settings
from agentarea_common.constants import MANAGED_BY_PLATFORM
from agentarea_common.infrastructure.secret_manager import BaseSecretManager
from agentarea_mcp.domain.mpc_server_instance_model import MCPServerInstance
from agentarea_mcp.infrastructure.repository import MCPServerInstanceRepository
from agentarea_mcp.mcp_events import EventSourceError, check_event_source, parse_arguments
from agentarea_secrets.catalog_service import (
    ManagedSecretError,
    SecretAccessDeniedError,
    SecretCatalogService,
    SecretNotFoundError,
)
from agentarea_streams.application.external_subscriptions import release_subscriber_secrets
from agentarea_streams.application.source_credentials import (
    credential_secret_name,
    issue_credential,
)
from agentarea_streams.application.stream_service import StreamService
from agentarea_streams.domain.source_types import SourceTypeEntry
from agentarea_streams.domain.verification import VerificationError, configured
from agentarea_streams.infrastructure.catalog_source_types import CatalogSourceTypeRepository
from agentarea_streams.infrastructure.orm import StreamSourceORM
from agentarea_streams.schemas import SecretRef, SourceCreate
from fastapi import HTTPException
from pydantic import ValidationError

SECRET_CONSUMER = "stream_source"  # noqa: S105 - a consumer type, not a credential


def public_webhook_url(webhook_id: str) -> str:
    """Where a provider posts a webhook source's events."""
    settings = get_app_settings()
    base = (settings.TELEGRAM_WEBHOOK_URL or settings.API_URL).rstrip("/")
    return f"{base}/webhooks/{webhook_id}"


async def source_type_entry(service: StreamService, slug: str) -> SourceTypeEntry:
    entry = await CatalogSourceTypeRepository(service.repository_factory.session).get(slug)
    if entry is None:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown source type {slug!r}; see GET /streams/source-types",
        )
    return entry


def _is_whsec(value: str) -> bool:
    if not value.startswith("whsec_"):
        return False
    try:
        decoded = base64.b64decode(value.removeprefix("whsec_"), validate=True)
    except binascii.Error, ValueError:
        return False
    return 24 <= len(decoded) <= 64


def check_source(entry: SourceTypeEntry, payload: SourceCreate) -> None:
    """Refuse what the entry cannot take, before anything is written."""
    name = entry.name
    if not entry.accepts(payload.kind.value):
        raise HTTPException(
            status_code=422,
            detail=f"{name} sources are {entry.delivery}, not {payload.kind.value}",
        )
    for given, declared, kind in (
        (payload.credentials, entry.credentials, "credential"),
        (payload.config, entry.config, "setting"),
    ):
        known = {f.key for f in declared}
        if unknown := sorted(set(given) - known):
            raise HTTPException(
                status_code=422,
                detail=f"{name} has no {kind} {', '.join(unknown)}; it takes {sorted(known)}",
            )
        for field in declared:
            value = given.get(field.key)
            if value == "":
                raise HTTPException(status_code=422, detail=f"{field.key} is empty")
            if field.required and value is None:
                raise HTTPException(status_code=422, detail=f"{name} needs {field.key}")
            if field.format == "whsec" and isinstance(value, str) and not _is_whsec(value):
                raise HTTPException(
                    status_code=422,
                    detail=f"{field.key} must be whsec_ and the base64 of 24 to 64 bytes",
                )
    if entry.verification is not None:
        try:
            configured(entry.verification, payload.config)
        except (ValidationError, VerificationError) as error:
            raise HTTPException(
                status_code=422, detail=f"{name} cannot verify with these settings: {error}"
            ) from error


def _speaks_mcp_events(entry: SourceTypeEntry) -> bool:
    return (entry.poll is not None and entry.poll.transport == "mcp_events") or (
        entry.registration is not None and entry.registration.transport == "mcp_events"
    )


async def mcp_events_config(
    payload: SourceCreate,
    *,
    load_instance: Callable[[UUID], Awaitable[MCPServerInstance | None]],
    authorize: Callable[[UUID], Awaitable[None]],
) -> dict[str, str]:
    """The config of an MCP Events source: an instance of this workspace the member may use
    that offers the event in the source's mode, with arguments its input schema takes.

    The Go event-service polls and subscribes through the mcp-manager gateway, which
    sends the instance's own headers and secret headers; an instance that authenticates
    through an auth config or is platform-managed is refused here rather than called
    without its credentials.
    """
    config = dict(payload.config)
    try:
        instance_id = UUID(config["mcp_instance_id"])
    except ValueError as error:
        raise HTTPException(status_code=422, detail="mcp_instance_id is not an id") from error
    instance = await load_instance(instance_id)
    if instance is None:
        raise HTTPException(status_code=422, detail=f"MCP server {instance_id} not found")
    await authorize(instance_id)
    if instance.auth_config_id is not None:
        raise HTTPException(
            status_code=422,
            detail="This MCP server signs in through an auth config; MCP Events sources take "
            "servers that authenticate with their own headers",
        )
    if instance.managed_by == MANAGED_BY_PLATFORM:
        raise HTTPException(
            status_code=422, detail="A platform-managed MCP server cannot be an event source"
        )
    try:
        arguments = parse_arguments(config.get("arguments"))
        check_event_source(
            instance.events, event=config["event"], arguments=arguments, mode=payload.kind.value
        )
    except EventSourceError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    config["mcp_instance_id"] = str(instance_id)
    config["arguments"] = json.dumps(arguments, sort_keys=True, separators=(",", ":"))
    return config


async def _usable_secret(
    catalog: SecretCatalogService, manager: BaseSecretManager, ref: SecretRef, field: str
) -> str:
    """The name of a workspace secret the caller may wire in; its value is not read."""
    try:
        secret = await catalog.get_for_use(ref.secret_id)
    except SecretNotFoundError as exc:
        raise HTTPException(
            status_code=422, detail=f"The secret chosen for {field} is not in this workspace"
        ) from exc
    except ManagedSecretError as exc:
        raise HTTPException(
            status_code=422, detail=f"The secret chosen for {field} must be a workspace secret"
        ) from exc
    except SecretAccessDeniedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if not await manager.has_secret(secret.secret_name):
        raise HTTPException(status_code=422, detail=f"The secret chosen for {field} has no value")
    return secret.secret_name


async def create_source(
    stream_id: UUID,
    payload: SourceCreate,
    *,
    service: StreamService,
    secret_manager: BaseSecretManager,
    secret_catalog: SecretCatalogService,
) -> tuple[StreamSourceORM, dict[str, str]]:
    """Create the source; return it and the credentials issued for it, shown this once.

    Every check runs before anything is written, so a refused request leaves
    nothing behind. A credential the entry marks ``issued`` and the member left
    out is generated: no source is left unsigned.
    """
    entry = await source_type_entry(service, payload.source_type)
    check_source(entry, payload)
    config = dict(payload.config)
    if _speaks_mcp_events(entry):
        instances = service.repository_factory.create_repository(MCPServerInstanceRepository)
        caller = service.repository_factory.user_context

        async def authorize(instance_id: UUID) -> None:
            await require_permission("use", "mcp_instance", str(instance_id), caller)

        config = await mcp_events_config(
            payload, load_instance=instances.get_by_id, authorize=authorize
        )

    stored: dict[str, Any] = {}
    references: list[tuple[UUID, str]] = []
    for key, value in payload.credentials.items():
        if isinstance(value, SecretRef):
            stored[key] = {
                "secret_name": await _usable_secret(secret_catalog, secret_manager, value, key)
            }
            references.append((value.secret_id, key))
        else:
            stored[key] = value
    issued = {
        field.key: issue_credential(field)
        for field in entry.credentials
        if field.issued and field.key not in stored
    }
    stored.update(issued)

    source = await service.add_source(
        stream_id=stream_id,
        kind=payload.kind,
        source_type=entry.slug,
        webhook_config=config,
        event_templates=(
            payload.event_templates.model_dump(exclude_none=True)
            if payload.event_templates
            else None
        ),
    )
    await secret_manager.set_secret(
        credential_secret_name(entry.slug, source.id), json.dumps(stored)
    )
    for secret_id, field in references:
        await secret_catalog.add_reference(secret_id, SECRET_CONSUMER, str(source.id), field)
    return source, issued


async def release_source(
    source: StreamSourceORM,
    *,
    secret_manager: BaseSecretManager,
    secret_catalog: SecretCatalogService,
) -> None:
    """Drop what a source holds outside its row: its credentials and their references."""
    if source.webhook_type is None or source.credential_key is None:
        return
    await secret_manager.delete_secret(
        credential_secret_name(source.webhook_type, source.credential_key)
    )
    await secret_catalog.clear_references(SECRET_CONSUMER, str(source.id))


async def delete_stream_with_sources(
    stream_id: UUID,
    *,
    service: StreamService,
    secret_manager: BaseSecretManager,
    secret_catalog: SecretCatalogService,
) -> None:
    """Delete a stream and release what its sources hold.

    Refused before anything is released while a trigger subscribes to it or a
    forward writes into it (``StreamInUseError``). Its MCP Events subscribers go
    with it, and their secrets.
    """
    await service.ensure_deletable(stream_id)
    for source in await service.list_sources(stream_id):
        await release_source(source, secret_manager=secret_manager, secret_catalog=secret_catalog)
    await release_subscriber_secrets(service, secret_manager, stream_id)
    await service.delete_stream(stream_id)
