"""Webhook sources a member adds to a stream directly, with no trigger.

A source holds no secret. Its credentials live in the secret store under
``channel_cred:{type}:{source_id}``, the name webhook intake reads them from,
as a trigger's do: a typed value is kept there, a picked workspace secret is
kept there only as ``{"secret_name": ...}`` and read at use. Shared by the REST
routes and the streams toolset.
"""

import json
import logging
import secrets
from typing import Any
from uuid import UUID

from agentarea_common.infrastructure.secret_manager import BaseSecretManager
from agentarea_secrets.catalog_service import (
    ManagedSecretError,
    SecretAccessDeniedError,
    SecretCatalogService,
    SecretNotFoundError,
)
from agentarea_streams.application.stream_service import StreamService
from agentarea_streams.infrastructure.orm import StreamSourceORM
from agentarea_streams.schemas import SecretRef, WebhookSourceCreate
from agentarea_triggers.channels.webhook_service import ChannelWebhookService
from agentarea_triggers.domain.source_types import StreamSourceType, get_stream_source_type
from agentarea_triggers.webhook_verification import (
    SIGNING_SECRET_KEYS,
    channel_credential_secret_name,
    signature_algorithm_error,
)
from fastapi import HTTPException

from ._trigger_creation import register_channel_webhook, with_webhook_secret_token

logger = logging.getLogger(__name__)

SECRET_CONSUMER = "stream_source"  # noqa: S105 - a consumer type, not a credential


def _source_type(webhook_type: str) -> StreamSourceType:
    source_type = get_stream_source_type(webhook_type)
    if source_type is None:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown source type {webhook_type!r}; see GET /streams/source-types",
        )
    return source_type


def _check_fields(source_type: StreamSourceType, payload: WebhookSourceCreate) -> None:
    name = source_type.name
    for given, declared, kind in (
        (payload.credentials, source_type.credentials, "credential"),
        (payload.config, source_type.config, "setting"),
    ):
        known = {f.key for f in declared}
        if unknown := sorted(set(given) - known):
            raise HTTPException(
                status_code=422,
                detail=f"{name} has no {kind} {', '.join(unknown)}; it takes {sorted(known)}",
            )
        for field in declared:
            value = given.get(field.key)
            if field.required and (value is None or value == ""):
                raise HTTPException(
                    status_code=422,
                    detail=f"{name} needs {field.key}: its verifier cannot run without it",
                )
            if value == "":
                raise HTTPException(status_code=422, detail=f"{field.key} is empty")
    if error := signature_algorithm_error(payload.config):
        raise HTTPException(status_code=422, detail=error)


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


async def _value_of(stored: Any, manager: BaseSecretManager) -> str:
    if isinstance(stored, dict):
        value = await manager.get_secret(str(stored["secret_name"]))
        if not value:
            raise HTTPException(
                status_code=422, detail=f"Secret {stored['secret_name']!r} has no value"
            )
        return value
    return str(stored)


async def create_webhook_source(
    stream_id: UUID,
    payload: WebhookSourceCreate,
    *,
    service: StreamService,
    secret_manager: BaseSecretManager,
    secret_catalog: SecretCatalogService,
    webhook_service: ChannelWebhookService,
) -> tuple[StreamSourceORM, str | None]:
    """Create the source; return it and the signing secret issued for it, if one was.

    Every check runs before anything is written, so a refused request leaves
    nothing behind. A source whose signing secret is optional and was not given
    gets one, returned here once and never again: no source is left unsigned.
    """
    source_type = _source_type(payload.webhook_type)
    _check_fields(source_type, payload)
    webhook_type = source_type.webhook_type

    stored: dict[str, Any] = {}
    references: list[tuple[UUID, str]] = []
    for key, value in payload.credentials.items():
        if isinstance(value, SecretRef):
            name = await _usable_secret(secret_catalog, secret_manager, value, key)
            stored[key] = {"secret_name": name}
            references.append((value.secret_id, key))
        else:
            stored[key] = value

    issued: str | None = None
    signing_key = SIGNING_SECRET_KEYS.get(webhook_type)
    optional = {f.key for f in source_type.credentials if not f.required}
    if signing_key in optional and signing_key not in stored:
        issued = secrets.token_urlsafe(32)
        stored[signing_key] = issued

    bot_token = (
        await _value_of(stored["bot_token"], secret_manager) if webhook_type == "telegram" else None
    )

    source = await service.add_webhook_source(
        stream_id=stream_id, webhook_type=webhook_type, validation_rules=dict(payload.config)
    )

    if bot_token is not None:
        stored, secret_token = with_webhook_secret_token(webhook_type, stored)
        try:
            webhook_service.webhook_url(str(source.webhook_id))
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"The Telegram webhook cannot be registered: {exc}",
            ) from exc
        await register_channel_webhook(
            webhook_service,
            channel_type=webhook_type,
            webhook_id=source.webhook_id,
            credentials={"bot_token": bot_token},
            secret_token=secret_token,
        )

    await secret_manager.set_secret(
        channel_credential_secret_name(webhook_type, source.id), json.dumps(stored)
    )
    for secret_id, field in references:
        await secret_catalog.add_reference(secret_id, SECRET_CONSUMER, str(source.id), field)
    logger.info("Created %s webhook source %s on stream %s", webhook_type, source.id, stream_id)
    return source, issued


async def release_webhook_source(
    source: StreamSourceORM,
    *,
    secret_manager: BaseSecretManager,
    secret_catalog: SecretCatalogService,
    webhook_service: ChannelWebhookService,
) -> None:
    """Drop what a standalone source holds outside its row: credentials, references, webhook."""
    if source.webhook_type is None:
        return
    secret_name = channel_credential_secret_name(source.webhook_type, source.id)
    if source.webhook_type == "telegram":
        raw = await secret_manager.get_secret(secret_name)
        stored = json.loads(raw) if raw else {}
        if stored.get("bot_token"):
            try:
                bot_token = await _value_of(stored["bot_token"], secret_manager)
                await webhook_service.deregister(
                    channel_type="telegram", credentials={"bot_token": bot_token}
                )
            except Exception:
                logger.warning(
                    "Telegram webhook of source %s could not be deregistered; the bot keeps "
                    "posting to a URL that now answers 400",
                    source.id,
                    exc_info=True,
                )
    await secret_manager.delete_secret(secret_name)
    await secret_catalog.clear_references(SECRET_CONSUMER, str(source.id))


async def delete_stream_with_sources(
    stream_id: UUID,
    *,
    service: StreamService,
    secret_manager: BaseSecretManager,
    secret_catalog: SecretCatalogService,
    webhook_service: ChannelWebhookService,
) -> None:
    """Delete a stream and release what its standalone sources hold.

    Refused before anything is released while a live webhook trigger's source
    feeds the stream (``SourceFedByTriggerError``), or while a trigger
    subscribes to it or a forward writes into it (``StreamInUseError``).
    """
    await service.ensure_deletable(stream_id)
    for source in await service.list_sources(stream_id):
        if source.credential_key == source.id:
            await release_webhook_source(
                source,
                secret_manager=secret_manager,
                secret_catalog=secret_catalog,
                webhook_service=webhook_service,
            )
    await service.delete_stream(stream_id)
