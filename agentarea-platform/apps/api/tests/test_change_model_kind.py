"""Switching a running task to a model it cannot converse with is refused up front."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from agentarea_api.api.v1.agents_tasks import _resolve_model_info
from fastapi import HTTPException


def _instance(kind: str):
    return SimpleNamespace(
        id=uuid4(),
        provider_config=SimpleNamespace(
            api_key="ref",
            managed_by=None,
            endpoint_url=None,
            provider_spec=SimpleNamespace(provider_type="openrouter", name="OpenRouter"),
        ),
        model_spec=SimpleNamespace(
            kind=kind,
            model_name="m",
            context_window=8000,
            max_output_tokens=None,
            input_cost_per_token=0,
            output_cost_per_token=0,
            display_name="M",
        ),
    )


class _Instances:
    def __init__(self, instance):
        self.instance = instance

    async def get(self, _id):
        return self.instance


@pytest.mark.parametrize("kind", ["image", "video", "decision", "embedding"])
async def test_a_non_chat_model_is_refused_with_409(kind):
    instance = _instance(kind)

    with pytest.raises(HTTPException) as refused:
        await _resolve_model_info(str(instance.id), _Instances(instance))  # type: ignore[arg-type]

    assert refused.value.status_code == 409
    assert kind in str(refused.value.detail)


async def test_a_chat_model_is_resolved():
    instance = _instance("chat")

    resolved = await _resolve_model_info(str(instance.id), _Instances(instance))  # type: ignore[arg-type]

    assert resolved["model_name"] == "m"
