"""OpenAI-compatible streaming usage/cost accounting."""

import json
from types import SimpleNamespace

import pytest

from agentarea_agents_sdk.models.llm_model import LLMModel, LLMRequest


class _Response:
    status_code = 200

    async def aiter_lines(self):
        yield "data: " + json.dumps(
            {
                "choices": [
                    {
                        "delta": {"content": "hello"},
                    }
                ]
            }
        )
        # OpenAI emits include_usage as a final chunk with an empty choices list.
        yield "data: " + json.dumps(
            {
                "choices": [],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                },
            }
        )
        yield "data: [DONE]"

    async def aclose(self):
        return None

    def raise_for_status(self):
        return None


class _Client:
    last_json = None

    def __init__(self, **_kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    def build_request(self, _method, _url, *, json, headers):  # noqa: ARG002
        type(self).last_json = json
        return object()

    async def send(self, _request, *, stream):  # noqa: ARG002
        return _Response()


@pytest.mark.asyncio
async def test_usage_only_final_chunk_is_not_dropped(monkeypatch):
    from agentarea_agents_sdk.models import llm_model as module

    monkeypatch.setattr(module.httpx, "AsyncClient", _Client)
    model = LLMModel(
        provider_type="openai",
        model_name="custom-model",
        endpoint_url="https://example.invalid/v1",
        input_cost_per_token=0.001,
        output_cost_per_token=0.002,
    )

    chunks = [
        chunk
        async for chunk in model._stream_openai_compatible(
            LLMRequest(messages=[{"role": "user", "content": "hi"}])
        )
    ]

    assert chunks[0].content == "hello"
    assert chunks[-1].usage is not None
    assert chunks[-1].usage.total_tokens == 15
    assert chunks[-1].cost == pytest.approx(0.02)
    assert _Client.last_json["stream_options"] == {"include_usage": True}


class _LiteLLMStream:
    def __init__(self):
        self._chunks = iter(
            [
                SimpleNamespace(
                    choices=[SimpleNamespace(delta=SimpleNamespace(content="hello"))],
                    _hidden_params={},
                ),
                SimpleNamespace(
                    choices=[],
                    usage=SimpleNamespace(
                        prompt_tokens=10,
                        completion_tokens=5,
                        total_tokens=15,
                    ),
                    _hidden_params={},
                ),
            ]
        )

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._chunks)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


@pytest.mark.asyncio
async def test_litellm_stream_requests_and_preserves_usage(monkeypatch):
    from agentarea_agents_sdk.models import llm_model as module

    captured = {}

    async def fake_acompletion(**params):
        captured.update(params)
        return _LiteLLMStream()

    monkeypatch.setattr(module.litellm, "acompletion", fake_acompletion)
    model = LLMModel(
        provider_type="openrouter",
        model_name="vendor/new-model",
        input_cost_per_token=0.001,
        output_cost_per_token=0.002,
    )

    chunks = [
        chunk
        async for chunk in model.ainvoke_stream(
            LLMRequest(messages=[{"role": "user", "content": "hi"}])
        )
    ]

    assert captured["stream_options"] == {"include_usage": True}
    assert chunks[0].content == "hello"
    assert chunks[-1].usage is not None
    assert chunks[-1].usage.total_tokens == 15
    assert chunks[-1].cost == pytest.approx(0.02)
