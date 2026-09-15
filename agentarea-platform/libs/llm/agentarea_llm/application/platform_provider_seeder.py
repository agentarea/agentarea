"""Install the models a deployment offers without anyone supplying a key.

An operator declares them once, in configuration; this turns that declaration into
the four rows the runtime needs (provider spec, provider config, model spec, model
instance) and leaves them owned by nobody in particular — readable from every
workspace, writable from none.

Deliberately idempotent and additive. It runs on startup, so it runs again on every
restart, every rollout and every replica; it must converge rather than accumulate,
and it must never remove a model an agent is configured to use just because someone
edited a list. Retiring a platform model is a deliberate act, not a side effect of a
config change — deactivate it and existing agents keep working while nothing new
selects it.

The credentials are not here. The configuration names a *reference*
(``credential: openai``) which the worker resolves from the environment at call
time; see ``agentarea_common.infrastructure.platform_credentials`` for why they
cannot live in the database.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4, uuid5

from agentarea_common.auth.context import UserContext
from agentarea_common.infrastructure.platform_credentials import MANAGED_BY_PLATFORM
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentarea_llm.domain.models import ModelInstance, ModelSpec, ProviderConfig, ProviderSpec

logger = logging.getLogger(__name__)

# The workspace platform-managed rows are written under.
#
# A real workspace id would work identically for reads — the repositories find
# these rows by managed_by, not by workspace — but it would make the platform's
# models appear to belong to whichever tenant happened to be first, and a
# workspace deletion would take them with it. A reserved value cannot collide with
# a Kratos identity id, which is what every real workspace id is.
PLATFORM_WORKSPACE_ID = "__platform__"
PLATFORM_ACTOR = "system:platform-provider-seeder"

# Namespace for deriving platform row ids from their names instead of minting random ones.
#
# A platform model's instance id is not an internal detail. It is what an agent stores
# when it selects the model, and what billing meters against — rate cards are keyed on it,
# and those live in a different service with its own database. A random id would have to
# be read out of this database and copied into that one by hand, per environment, after
# every fresh install; and the price of a model would then be tied to a row somebody could
# recreate by accident.
#
# Derived from (provider_key, model_name), so the same model has the same id in staging,
# in production, and in a local database created this morning. Rate cards can name it in a
# migration, and re-seeding is genuinely idempotent even against an empty database.
#
# A fixed, arbitrary UUID; its only job is to keep these names from colliding with
# anything else's uuid5 in the same table.
PLATFORM_ID_NAMESPACE = UUID("8f3d4b2a-6c1e-5a7f-9d0b-2e4a6c8f1d3b")


def platform_config_id(provider_key: str) -> UUID:
    """The id of the platform's provider configuration for this provider."""
    return uuid5(PLATFORM_ID_NAMESPACE, f"provider_config:{provider_key}")


def platform_instance_id(provider_key: str, model_name: str) -> UUID:
    """The id of the platform's model instance for this model.

    This is the value a rate card's ``resource_ref`` must carry to price the model.
    """
    return uuid5(PLATFORM_ID_NAMESPACE, f"model_instance:{provider_key}:{model_name}")


@dataclass(frozen=True)
class PlatformModel:
    """One model the deployment offers."""

    model_name: str
    display_name: str
    context_window: int
    # Priced in the provider's own units, per token, exactly as a tenant's own
    # model spec is. The runtime refuses to start a call on a model with no
    # pricing — it cannot enforce a run budget without one — so these are
    # required rather than optional, and a missing price is a configuration error
    # caught here instead of a workflow failure later.
    input_cost_per_token: float
    output_cost_per_token: float
    max_output_tokens: int | None = None
    description: str | None = None
    supports_function_calling: bool = True
    supports_vision: bool = False
    supports_reasoning: bool = False


@dataclass(frozen=True)
class PlatformProvider:
    """One provider the deployment supplies credentials for."""

    # Must match an existing provider_specs.provider_key. Not created here: the
    # spec describes a provider type (its litellm identity, its icon), which is
    # catalog data, not a deployment decision.
    provider_key: str
    name: str
    # Resolved from the environment at call time, not stored. None for an
    # endpoint that authenticates with nothing.
    credential: str | None = None
    endpoint_url: str | None = None
    models: list[PlatformModel] = field(default_factory=list)


class PlatformProviderSeeder:
    """Converges the database on the declared set of platform providers."""

    def __init__(self, session: AsyncSession):
        self.session = session

    @property
    def context(self) -> UserContext:
        """The identity platform rows are written under."""
        return UserContext(user_id=PLATFORM_ACTOR, workspace_id=PLATFORM_WORKSPACE_ID)

    async def seed(self, providers: list[PlatformProvider]) -> dict[str, int]:
        """Install every declared provider and its models. Returns a count summary."""
        summary = {"providers": 0, "models": 0, "skipped": 0}
        for provider in providers:
            try:
                created_models = await self._seed_provider(provider)
            except Exception:
                # One misconfigured provider must not cost the deployment the
                # others — nor the API its startup. A provider that failed to seed
                # simply has no models, which is visible and recoverable; a failed
                # boot is neither.
                logger.exception(
                    "Failed to seed platform provider %r; continuing", provider.provider_key
                )
                summary["skipped"] += 1
                continue
            summary["providers"] += 1
            summary["models"] += created_models
        await self.session.commit()
        return summary

    async def _seed_provider(self, provider: PlatformProvider) -> int:
        spec = await self._require_provider_spec(provider.provider_key)
        config = await self._upsert_config(provider, spec)
        created = 0
        for model in provider.models:
            if await self._upsert_model(config, spec, model):
                created += 1
        return created

    async def _require_provider_spec(self, provider_key: str) -> ProviderSpec:
        """Find the provider spec this configuration attaches to.

        Missing is a hard error for this provider: the spec carries the litellm
        provider_type the runtime dispatches on, and inventing one here would
        produce a model that lists fine and fails on first use.
        """
        result = await self.session.execute(
            select(ProviderSpec).where(ProviderSpec.provider_key == provider_key)
        )
        spec = result.scalar_one_or_none()
        if spec is None:
            raise LookupError(
                f"No provider spec for {provider_key!r}. The provider catalog must be "
                "loaded before platform providers can be seeded."
            )
        return spec

    async def _upsert_config(
        self, provider: PlatformProvider, spec: ProviderSpec
    ) -> ProviderConfig:
        """Create or update the platform's configuration for this provider.

        Matched on (provider_spec_id, managed_by) rather than on name, so renaming
        a provider in configuration updates the existing row instead of orphaning
        it and creating a second one that shadows the first.
        """
        result = await self.session.execute(
            select(ProviderConfig).where(
                ProviderConfig.provider_spec_id == spec.id,
                ProviderConfig.managed_by == MANAGED_BY_PLATFORM,
            )
        )
        config = result.scalar_one_or_none()

        if config is None:
            config = ProviderConfig(
                id=platform_config_id(provider.provider_key),
                provider_spec_id=spec.id,
                workspace_id=PLATFORM_WORKSPACE_ID,
                created_by=PLATFORM_ACTOR,
                managed_by=MANAGED_BY_PLATFORM,
            )
            self.session.add(config)

        config.name = provider.name
        # The credential reference, not a secret name: nothing reads this through
        # the workspace-scoped secret manager, and api_key_secret_id stays NULL so
        # the secret-catalog machinery has nothing to account for.
        config.api_key = provider.credential
        config.endpoint_url = provider.endpoint_url
        config.is_active = True
        # is_public governs visibility *within* a workspace. Cross-workspace
        # visibility comes from managed_by, in the repository; setting this too
        # would be a second answer to a question already answered.
        config.is_public = True
        await self.session.flush()
        return config

    async def _upsert_model(
        self, config: ProviderConfig, spec: ProviderSpec, model: PlatformModel
    ) -> bool:
        """Ensure this model exists and is instantiated. True if newly instantiated."""
        model_spec = await self._upsert_model_spec(spec, model)
        return await self._upsert_instance(config, model_spec, model, spec.provider_key)

    async def _upsert_model_spec(self, spec: ProviderSpec, model: PlatformModel) -> ModelSpec:
        """Find or create the model spec.

        Looked up WITHOUT a workspace filter on purpose. ``uq_model_specs_provider_model``
        is (provider_spec_id, model_name) and does not include workspace_id, so a
        spec for this model may already exist because some tenant added it first.
        A workspace-scoped lookup would miss it and the insert would then violate
        that constraint — which is the same trap ``_find_global_by_provider_and_model``
        exists to avoid on the tenant path.
        """
        result = await self.session.execute(
            select(ModelSpec).where(
                ModelSpec.provider_spec_id == spec.id,
                ModelSpec.model_name == model.model_name,
            )
        )
        model_spec = result.scalar_one_or_none()

        if model_spec is None:
            model_spec = ModelSpec(
                id=uuid4(),
                provider_spec_id=spec.id,
                model_name=model.model_name,
                workspace_id=PLATFORM_WORKSPACE_ID,
                created_by=PLATFORM_ACTOR,
            )
            self.session.add(model_spec)
        elif model_spec.workspace_id != PLATFORM_WORKSPACE_ID:
            # A tenant got here first. Their row is left exactly as it is —
            # including their pricing, which is theirs to have got wrong — because
            # overwriting it would silently reprice their own usage of the same
            # model. The platform instance simply points at it.
            logger.info(
                "Model spec %s/%s already exists in workspace %s; reusing it unchanged",
                spec.provider_key,
                model.model_name,
                model_spec.workspace_id,
            )
            await self.session.flush()
            return model_spec

        model_spec.display_name = model.display_name
        model_spec.description = model.description
        model_spec.context_window = model.context_window
        model_spec.max_output_tokens = model.max_output_tokens
        model_spec.input_cost_per_token = model.input_cost_per_token
        model_spec.output_cost_per_token = model.output_cost_per_token
        model_spec.supports_function_calling = model.supports_function_calling
        model_spec.supports_vision = model.supports_vision
        model_spec.supports_reasoning = model.supports_reasoning
        model_spec.is_active = True
        await self.session.flush()
        return model_spec

    async def _upsert_instance(
        self,
        config: ProviderConfig,
        model_spec: ModelSpec,
        model: PlatformModel,
        provider_key: str,
    ) -> bool:
        """Ensure the instance agents actually select exists. True if created.

        The instance id is what an agent stores and what billing meters against, so
        it must be stable across restarts — hence find-then-create rather than
        delete-and-recreate. Recreating it would silently unlink every agent
        configured to use this model and reset its metered history to a new
        resource.
        """
        result = await self.session.execute(
            select(ModelInstance).where(
                ModelInstance.provider_config_id == config.id,
                ModelInstance.model_spec_id == model_spec.id,
            )
        )
        instance = result.scalar_one_or_none()
        created = instance is None

        if instance is None:
            instance = ModelInstance(
                id=platform_instance_id(provider_key, model.model_name),
                provider_config_id=config.id,
                model_spec_id=model_spec.id,
                workspace_id=PLATFORM_WORKSPACE_ID,
                created_by=PLATFORM_ACTOR,
            )
            self.session.add(instance)

        instance.name = model.display_name
        instance.description = model.description
        instance.is_active = True
        instance.is_public = True
        await self.session.flush()
        return created


def parse_platform_providers(raw: Any) -> list[PlatformProvider]:
    """Build the declared provider list from configuration.

    Validated strictly and early. This runs at startup, where a typo can still be
    reported as a startup error against a named field; the alternative is a model
    that lists correctly and fails on first use with a message about the provider.
    """
    if not raw:
        return []
    if not isinstance(raw, list):
        raise ValueError("platform providers must be a list")

    providers: list[PlatformProvider] = []
    for index, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise ValueError(f"platform provider #{index} must be an object")
        try:
            provider_key = entry["provider_key"]
        except KeyError as exc:
            raise ValueError(f"platform provider #{index} is missing provider_key") from exc

        models = []
        for model_index, model_entry in enumerate(entry.get("models") or []):
            where = f"{provider_key} model #{model_index}"
            if not isinstance(model_entry, dict):
                raise ValueError(f"{where} must be an object")
            missing = {
                "model_name",
                "context_window",
                "input_cost_per_token",
                "output_cost_per_token",
            } - model_entry.keys()
            if missing:
                raise ValueError(f"{where} is missing {', '.join(sorted(missing))}")
            models.append(
                PlatformModel(
                    model_name=model_entry["model_name"],
                    display_name=model_entry.get("display_name") or model_entry["model_name"],
                    description=model_entry.get("description"),
                    context_window=int(model_entry["context_window"]),
                    max_output_tokens=(
                        int(model_entry["max_output_tokens"])
                        if model_entry.get("max_output_tokens")
                        else None
                    ),
                    input_cost_per_token=float(model_entry["input_cost_per_token"]),
                    output_cost_per_token=float(model_entry["output_cost_per_token"]),
                    supports_function_calling=bool(
                        model_entry.get("supports_function_calling", True)
                    ),
                    supports_vision=bool(model_entry.get("supports_vision", False)),
                    supports_reasoning=bool(model_entry.get("supports_reasoning", False)),
                )
            )

        providers.append(
            PlatformProvider(
                provider_key=provider_key,
                name=entry.get("name") or provider_key,
                credential=entry.get("credential"),
                endpoint_url=entry.get("endpoint_url"),
                models=models,
            )
        )
    return providers


async def platform_model_instance_ids(session: AsyncSession) -> list[UUID]:
    """Every model instance the platform supplies.

    Exposed for the operator-facing check "what am I actually offering, and what
    should have a rate card", which is otherwise a three-table join nobody will
    write correctly under time pressure.
    """
    result = await session.execute(
        select(ModelInstance.id)
        .join(ProviderConfig, ProviderConfig.id == ModelInstance.provider_config_id)
        .where(ProviderConfig.managed_by == MANAGED_BY_PLATFORM)
    )
    return list(result.scalars().all())
