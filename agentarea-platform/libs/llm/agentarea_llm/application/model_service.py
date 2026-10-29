"""Resolve a model instance into a typed client for the kind a surface needs."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import fields
from typing import Any, Protocol
from uuid import UUID

import httpx
from agentarea_common.auth.context import UserContext
from agentarea_common.model_charges import ModelFunding
from agentarea_common.utils.outbound_tls import outbound_ssl_context
from agentarea_common.utils.url_safety import endpoint_policy_for, safe_async_client
from agentarea_secrets.secret_manager_factory import SecretManagerFactory
from sqlalchemy.ext.asyncio import AsyncSession

from agentarea_llm.application.provider_credentials import resolve_provider_api_key
from agentarea_llm.domain.models import ModelInstance, ModelKind
from agentarea_llm.infrastructure.model_clients import (
    DecisionModel,
    ImageModel,
    ModelEndpoint,
    ModelTarget,
    VideoModel,
)
from agentarea_llm.infrastructure.model_instance_repository import ModelInstanceRepository

# (secret reference, managed_by, funding) -> the credential, read from the workspace
# that owns it; the platform's only for a funded call.
ApiKeyResolver = Callable[[str | None, str | None, ModelFunding | None], Awaitable[str | None]]
EndpointHttpClientFactory = Callable[[ModelEndpoint], httpx.AsyncClient]

_HTTP_TIMEOUT = httpx.Timeout(120.0, connect=10.0)


class ModelUnavailableError(LookupError):
    """The instance does not exist, is inactive, or borrows a part it may not use."""


class ModelKindMismatchError(ValueError):
    """The instance's model is of a different kind than the surface accepts."""


class _InstanceSource(Protocol):
    async def get_with_relations(self, id: UUID) -> Any: ...


def default_http_client(endpoint: ModelEndpoint) -> httpx.AsyncClient:
    """A plain client for the provider's own address; an SSRF-guarded one for a member's."""
    policy = endpoint_policy_for(endpoint.managed_by) if endpoint.endpoint_url else None
    if policy is not None:
        return safe_async_client(policy=policy, timeout=_HTTP_TIMEOUT)
    return httpx.AsyncClient(timeout=_HTTP_TIMEOUT, verify=outbound_ssl_context())


class ModelService:
    """One place that turns ``instance_id`` into a client, refusing the wrong kind loudly."""

    def __init__(
        self,
        *,
        instances: _InstanceSource,
        api_key_resolver: ApiKeyResolver,
        http_client_factory: EndpointHttpClientFactory = default_http_client,
    ) -> None:
        self._instances = instances
        self._resolve_api_key = api_key_resolver
        self._http_client_factory = http_client_factory

    async def describe(self, instance_id: UUID | str, kind: ModelKind) -> ModelTarget:
        """The instance a call of ``kind`` would run on, without its credential.

        A call is funded from this (``hold_model_call``), and only then connected.
        """
        instance_uuid = instance_id if isinstance(instance_id, UUID) else UUID(str(instance_id))
        instance: ModelInstance | None = await self._instances.get_with_relations(instance_uuid)
        if instance is None:
            raise ModelUnavailableError(f"Model instance {instance_uuid} not found")
        if not instance.is_active:
            raise ModelUnavailableError(f"Model instance {instance_uuid} is inactive")
        foreign = instance.foreign_part()
        if foreign is not None:
            raise ModelUnavailableError(
                f"Model instance {instance_uuid} uses a {foreign} from another workspace"
            )
        actual = instance.model_spec.kind
        if actual != kind.value:
            raise ModelKindMismatchError(
                f"Model instance {instance_uuid} is a {actual} model; a {kind.value} model is required"
            )
        config = instance.provider_config
        spec = instance.model_spec
        return ModelTarget(
            instance_id=str(instance_uuid),
            provider_type=config.provider_spec.provider_type,
            model_name=spec.model_name,
            endpoint_url=config.endpoint_url,
            managed_by=config.managed_by,
            api_key_reference=config.api_key,
            input_cost_per_token=spec.input_cost_per_token,
            output_cost_per_token=spec.output_cost_per_token,
            max_output_tokens=getattr(spec, "max_output_tokens", None),
            output_cost_per_image=getattr(spec, "output_cost_per_image", None),
            output_cost_per_video_per_second=getattr(
                spec, "output_cost_per_video_per_second", None
            ),
            provider=config.provider_spec.profile(),
        )

    async def connect(self, target: ModelTarget, funding: ModelFunding) -> ModelEndpoint:
        """The target with its credential, read for the call ``funding`` pays for."""
        if funding.model_instance_id != target.instance_id:
            raise ValueError(
                f"funding for model {funding.model_instance_id} cannot pay a call on "
                f"{target.instance_id}"
            )
        return ModelEndpoint(
            **{field.name: getattr(target, field.name) for field in fields(ModelTarget)},
            api_key=await self._resolve_api_key(
                target.api_key_reference, target.managed_by, funding
            ),
        )

    async def image_model(self, target: ModelTarget, funding: ModelFunding) -> ImageModel:
        return ImageModel(await self.connect(target, funding))

    async def video_model(self, target: ModelTarget, funding: ModelFunding) -> VideoModel:
        endpoint = await self.connect(target, funding)
        return VideoModel(endpoint, http_client_factory=lambda: self._http_client_factory(endpoint))

    async def decision_model(self, target: ModelTarget, funding: ModelFunding) -> DecisionModel:
        endpoint = await self.connect(target, funding)
        return DecisionModel(
            endpoint, http_client_factory=lambda: self._http_client_factory(endpoint)
        )


def build_model_service(
    *,
    session: AsyncSession,
    user_context: UserContext,
    secret_manager_factory: SecretManagerFactory,
) -> ModelService:
    """A ModelService reading instances and credentials as ``user_context``'s workspace."""

    async def resolve(
        reference: str | None, managed_by: str | None, funding: ModelFunding | None
    ) -> str | None:
        return await resolve_provider_api_key(
            reference=reference,
            managed_by=managed_by,
            funding=funding,
            user_context=user_context,
            secret_manager_factory=secret_manager_factory,
        )

    return ModelService(
        instances=ModelInstanceRepository(session, user_context), api_key_resolver=resolve
    )
