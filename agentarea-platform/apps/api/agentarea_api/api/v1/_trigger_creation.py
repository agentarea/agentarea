"""Creating a trigger end to end, shared by the trigger and agent routes.

A trigger is more than its row: channel credentials are resolved from workspace
secrets, copied into the secret store for outbound delivery, and the channel's
webhook is registered with the provider. Creating an agent with triggers runs
exactly the same steps, so they live here once.
"""

import json
import logging
from typing import Any
from uuid import UUID

from agentarea_common.auth.context import UserContext
from agentarea_common.config.app import get_app_settings
from agentarea_common.infrastructure.secret_manager import BaseSecretManager
from agentarea_secrets.catalog_service import (
    ManagedSecretError,
    SecretAccessDeniedError,
    SecretCatalogService,
    SecretNotFoundError,
)
from agentarea_triggers.channels.webhook_service import ChannelWebhookService
from agentarea_triggers.domain.models import Trigger
from agentarea_triggers.domain.models import TriggerCreate as DomainTriggerCreate
from agentarea_triggers.extractors import resolves_own_credentials
from agentarea_triggers.schemas.dto import TriggerSpec
from agentarea_triggers.trigger_service import TriggerService
from agentarea_triggers.webhook_verification import channel_credential_secret_name
from fastapi import HTTPException

logger = logging.getLogger(__name__)


def get_channel_webhook_service() -> ChannelWebhookService:
    """Composition root for inbound webhook registration.

    Reads the reachable ingress base (TELEGRAM_WEBHOOK_BASE_URL if set, else
    API_BASE_URL) and hands the endpoints a service that knows nothing about any
    specific channel — that lives behind the WebhookRegistrar registry.
    """
    settings = get_app_settings()
    base = getattr(settings, "TELEGRAM_WEBHOOK_BASE_URL", "") or settings.API_BASE_URL
    return ChannelWebhookService(base)


async def resolve_channel_credentials(
    credentials: dict[str, Any] | None,
    secret_catalog: SecretCatalogService,
    secret_manager: BaseSecretManager,
) -> dict[str, Any] | None:
    """Resolve workspace secret selections before persisting any trigger changes."""
    if not credentials:
        return credentials

    resolved = {}
    for field, credential in credentials.items():
        if not isinstance(credential, dict):
            # Existing clients provide credential values directly.
            resolved[field] = credential
            continue

        if set(credential) != {"secret_id"} or not isinstance(credential["secret_id"], str):
            raise HTTPException(
                status_code=422, detail="Invalid channel credential secret reference."
            )
        try:
            secret_id = UUID(credential["secret_id"])
        except ValueError as exc:
            raise HTTPException(
                status_code=422, detail="Invalid channel credential secret reference."
            ) from exc

        try:
            secret = await secret_catalog.get_for_use(secret_id)
        except SecretNotFoundError as exc:
            raise HTTPException(
                status_code=422,
                detail="Selected channel credential secret is not available in this workspace.",
            ) from exc
        except ManagedSecretError as exc:
            raise HTTPException(
                status_code=422,
                detail="Selected channel credential must be a user-owned workspace secret.",
            ) from exc
        except SecretAccessDeniedError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        try:
            value = await secret_manager.get_secret(secret.secret_name)
        except Exception:
            # Provider exceptions may include sensitive material; never forward or log them.
            raise HTTPException(
                status_code=422, detail="Selected channel credential secret could not be read."
            ) from None
        if not value:
            raise HTTPException(
                status_code=422, detail="Selected channel credential secret has no value."
            )
        resolved[field] = value

    return resolved


def build_domain_trigger(
    spec: TriggerSpec,
    agent_id: UUID,
    user_context: UserContext,
    credentials: dict[str, Any] | None,
) -> DomainTriggerCreate:
    """The domain create for ``spec``, with polling credentials folded in.

    Polling extractors read their credentials from ``data_extractor_config`` (the
    Go polling service does). Extractors that read the secret store themselves
    are excluded: that column is plain JSON, and a mailbox password does not
    belong in it.
    """
    trigger_data = spec.to_domain_for(
        agent_id,
        created_by=user_context.user_id,
        workspace_id=user_context.workspace_id,
    )
    if (
        trigger_data.data_extractor
        and credentials
        and not resolves_own_credentials(trigger_data.data_extractor)
    ):
        trigger_data.data_extractor_config = {
            **(trigger_data.data_extractor_config or {}),
            **credentials,
        }
    return trigger_data


def _channel_type(spec: TriggerSpec) -> str:
    # Extractor names like "telegram_polling" map to a channel type by suffix.
    extractor = spec.data_extractor or ""
    return spec.webhook_type or extractor.removesuffix("_polling") or "generic"


async def create_trigger_from_spec(
    spec: TriggerSpec,
    *,
    agent_id: UUID,
    user_context: UserContext,
    credentials: dict[str, Any] | None,
    trigger_service: TriggerService,
    secret_manager: BaseSecretManager,
    webhook_service: ChannelWebhookService,
) -> tuple[Trigger, bool]:
    """Create one trigger with its credentials and webhook; return it and whether it has credentials.

    ``credentials`` must already be resolved (see ``resolve_channel_credentials``).
    A spec with ``enabled=False`` is created and then disabled, so a schedule
    never fires before its owner switches it on.
    """
    trigger = await trigger_service.create_trigger(
        build_domain_trigger(spec, agent_id, user_context, credentials)
    )

    has_creds = False
    if credentials and secret_manager:
        secret_name = channel_credential_secret_name(_channel_type(spec), trigger.id)
        await secret_manager.set_secret(secret_name, json.dumps(credentials))
        has_creds = True
        logger.info(f"Stored channel credentials for trigger {trigger.id}")

    if has_creds:
        await webhook_service.register(
            channel_type=getattr(trigger, "webhook_type", None),
            webhook_id=getattr(trigger, "webhook_id", None),
            credentials=credentials,
        )

    if not spec.enabled:
        await trigger_service.disable_trigger(trigger.id)
        trigger.is_active = False

    return trigger, has_creds


async def discard_trigger(
    trigger: Trigger,
    spec: TriggerSpec,
    credentials: dict[str, Any] | None,
    *,
    trigger_service: TriggerService,
    secret_manager: BaseSecretManager,
    webhook_service: ChannelWebhookService,
) -> None:
    """Undo ``create_trigger_from_spec``: webhook, stored credentials, then the trigger."""
    if credentials:
        try:
            await webhook_service.deregister(
                channel_type=getattr(trigger, "webhook_type", None),
                credentials=credentials,
            )
        except Exception as e:
            logger.warning(f"Webhook deregistration failed for {trigger.id}: {e}", exc_info=True)
        if secret_manager:
            await secret_manager.delete_secret(
                channel_credential_secret_name(_channel_type(spec), trigger.id)
            )
    await trigger_service.delete_trigger(trigger.id)
