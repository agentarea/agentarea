"""A model instance says whether it runs on the platform's credentials, and its tags.

The webapp preselects the platform model tagged ``default`` for a new agent, and
the instance list is all it has to pick from. ``managed_by`` lives on the provider
configuration, so the response has to carry it across — without it the picker
could not tell an included model from one the workspace pays a provider for.
"""

import uuid
from datetime import UTC, datetime

from agentarea_api.api.v1.model_instances import ModelInstanceResponse
from agentarea_common.constants import MANAGED_BY_PLATFORM
from agentarea_llm.domain.models import ModelInstance, ModelSpec, ProviderConfig

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _instance(provider_config: ProviderConfig | None, tags: list[str]) -> ModelInstance:
    return ModelInstance(
        id=uuid.uuid4(),
        provider_config_id=uuid.uuid4(),
        model_spec_id=uuid.uuid4(),
        name="Kimi",
        is_active=True,
        is_public=False,
        tags=tags,
        created_at=NOW,
        updated_at=NOW,
        provider_config=provider_config,
        model_spec=ModelSpec(model_name="kimi-k2.6", display_name="Kimi K2.6"),
    )


def test_an_instance_on_a_platform_config_is_marked_platform():
    config = ProviderConfig(name="AgentArea (included)", managed_by=MANAGED_BY_PLATFORM)

    response = ModelInstanceResponse.from_domain(_instance(config, ["default", "fast"]))

    assert response.managed_by == MANAGED_BY_PLATFORM
    assert response.tags == ["default", "fast"]
    assert response.model_name == "kimi-k2.6"


def test_an_instance_on_the_workspace_own_key_is_not():
    response = ModelInstanceResponse.from_domain(_instance(ProviderConfig(name="My key"), []))

    assert response.managed_by is None
    assert response.tags == []
