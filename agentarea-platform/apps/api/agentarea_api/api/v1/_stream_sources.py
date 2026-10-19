"""Sources a member adds to a stream: a webhook or poll source of a catalog entry.

A source holds no secret. Its credentials live in the secret store under
``channel_cred:{slug}:{source_id}``: a typed value is kept there, a picked
workspace secret only as ``{"secret_name": ...}`` and read at use. Registering
a webhook with the provider (Telegram's setWebhook) is the Go reconciler's job.
Shared by the REST routes and the streams toolset.
"""

import json
import logging
import secrets
from typing import Any
from uuid import UUID

from agentarea_common.config.app import get_app_settings
from agentarea_common.infrastructure.secret_manager import BaseSecretManager
from agentarea_secrets.catalog_service import (
    ManagedSecretError,
    SecretAccessDeniedError,
    SecretCatalogService,
    SecretNotFoundError,
)
from agentarea_streams.application.source_credentials import credential_secret_name
from agentarea_streams.application.stream_service import StreamService
from agentarea_streams.domain.source_types import SourceTypeEntry
from agentarea_streams.domain.verification import VerificationError, configured
from agentarea_streams.infrastructure.catalog_source_types import CatalogSourceTypeRepository
from agentarea_streams.infrastructure.orm import StreamSourceORM
from agentarea_streams.schemas import SecretRef, SourceCreate
from fastapi import HTTPException
from pydantic import ValidationError

logger = logging.getLogger(__name__)

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
    if entry.verification is not None:
        try:
            configured(entry.verification, payload.config)
        except (ValidationError, VerificationError) as error:
            raise HTTPException(
                status_code=422, detail=f"{name} cannot verify with these settings: {error}"
            ) from error


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
        field.key: secrets.token_urlsafe(32)
        for field in entry.credentials
        if field.issued and field.key not in stored
    }
    stored.update(issued)

    source = await service.add_source(
        stream_id=stream_id,
        kind=payload.kind,
        source_type=entry.slug,
        webhook_config=dict(payload.config),
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
    logger.info("Created source %s on stream %s", source.id, stream_id)
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
    forward writes into it (``StreamInUseError``).
    """
    await service.ensure_deletable(stream_id)
    for source in await service.list_sources(stream_id):
        await release_source(source, secret_manager=secret_manager, secret_catalog=secret_catalog)
    await service.delete_stream(stream_id)
