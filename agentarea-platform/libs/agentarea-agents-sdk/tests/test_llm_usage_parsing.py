"""Provider usage reads the same whatever shape the provider reports it in.

Cached prompt tokens are kept apart so a call that hit the cache is priced at
the model's cached-input rate, and a usage block without ``total_tokens`` is
still accounted, not mistaken for a provider that reported nothing.
"""

import json
from decimal import Decimal

import pytest
from litellm.types.utils import ModelResponse, Usage

from agentarea_agents_sdk.models.llm_model import (
    LLMModel,
    LLMProviderHTTPError,
    LLMRequest,
    LLMUsage,
    provider_reported_cost,
    usage_from_provider,
)


def test_openai_cached_tokens_are_read_from_prompt_details():
    usage = usage_from_provider(
        {
            "prompt_tokens": 1000,
            "completion_tokens": 50,
            "total_tokens": 1050,
            "prompt_tokens_details": {"cached_tokens": 800},
        }
    )

    assert usage == LLMUsage(
        prompt_tokens=1000, completion_tokens=50, total_tokens=1050, cached_prompt_tokens=800
    )


def test_anthropic_shape_counts_cache_reads_and_writes_into_the_prompt():
    usage = usage_from_provider(
        {
            "input_tokens": 100,
            "output_tokens": 20,
            "cache_read_input_tokens": 700,
            "cache_creation_input_tokens": 200,
        }
    )

    assert usage == LLMUsage(
        prompt_tokens=1000,
        completion_tokens=20,
        total_tokens=1020,
        cached_prompt_tokens=700,
        cache_creation_tokens=200,
    )


def test_deepseek_cache_hits_are_cached_tokens():
    usage = usage_from_provider(
        {
            "prompt_tokens": 500,
            "completion_tokens": 10,
            "total_tokens": 510,
            "prompt_cache_hit_tokens": 300,
            "prompt_cache_miss_tokens": 200,
        }
    )

    assert usage.cached_prompt_tokens == 300


def test_litellm_usage_object_keeps_its_cached_tokens():
    usage = usage_from_provider(
        Usage(
            prompt_tokens=400,
            completion_tokens=40,
            total_tokens=440,
            prompt_tokens_details={"cached_tokens": 256},
        )
    )

    assert (usage.prompt_tokens, usage.cached_prompt_tokens, usage.total_tokens) == (400, 256, 440)


@pytest.mark.parametrize(
    "raw",
    [
        {"prompt_tokens": 10, "completion_tokens": 5},
        {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": None},
        {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 0},
    ],
    ids=["absent", "null", "zero"],
)
def test_a_missing_total_is_the_sum_of_its_parts(raw):
    assert usage_from_provider(raw).total_tokens == 15


def test_nothing_reported_stays_nothing():
    assert usage_from_provider({"prompt_tokens": None, "completion_tokens": None}).total_tokens == 0


def _model(cached_rate: str | None) -> LLMModel:
    return LLMModel(
        provider_type="openai",
        model_name="m",
        input_cost_per_token=Decimal("0.001"),
        output_cost_per_token=Decimal("0.002"),
        cached_input_cost_per_token=Decimal(cached_rate) if cached_rate is not None else None,
    )


def test_cached_prompt_tokens_are_priced_at_the_cached_rate():
    usage = LLMUsage(
        prompt_tokens=1000, completion_tokens=100, total_tokens=1100, cached_prompt_tokens=800
    )

    # 200 fresh * 0.001 + 800 cached * 0.0001 + 100 out * 0.002
    assert _model("0.0001")._configured_cost(usage) == Decimal("0.48")


def test_cache_writes_are_priced_at_their_own_rate_when_declared():
    usage = LLMUsage(
        prompt_tokens=1000,
        completion_tokens=100,
        total_tokens=1100,
        cached_prompt_tokens=700,
        cache_creation_tokens=200,
    )
    model = LLMModel(
        provider_type="anthropic",
        model_name="m",
        input_cost_per_token=Decimal("0.001"),
        output_cost_per_token=Decimal("0.002"),
        cached_input_cost_per_token=Decimal("0.0001"),
        cache_creation_input_cost_per_token=Decimal("0.00125"),
    )

    # 100 fresh * 0.001 + 700 read * 0.0001 + 200 written * 0.00125 + 100 out * 0.002
    assert model._configured_cost(usage) == Decimal("0.62")
    # Without a write rate a written token costs what a fresh one does.
    assert _model("0.0001")._configured_cost(usage) == Decimal("0.57")


def test_without_a_cached_rate_every_prompt_token_is_full_price():
    usage = LLMUsage(
        prompt_tokens=1000, completion_tokens=100, total_tokens=1100, cached_prompt_tokens=800
    )

    assert _model(None)._configured_cost(usage) == Decimal("1.2")


class _Response:
    def __init__(self, status_code: int, lines: list[str], body: bytes = b""):
        self.status_code = status_code
        self._lines = lines
        self._body = body

    async def aiter_lines(self):
        for line in self._lines:
            yield line

    async def aread(self):
        return self._body

    async def aclose(self):
        return None


def _client(responses: list[_Response]):
    class _Client:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        def build_request(self, _method, _url, *, json, headers):  # noqa: ARG002
            return object()

        async def send(self, _request, *, stream):  # noqa: ARG002
            return responses.pop(0)

    return _Client


async def _stream(monkeypatch, responses: list[_Response]) -> list:
    from agentarea_agents_sdk.models import llm_model as module

    monkeypatch.setattr(module.httpx, "AsyncClient", _client(responses))
    model = _model("0.0001")
    model.endpoint_url = "https://gateway.example/v1"
    return [
        chunk
        async for chunk in model._stream_openai_compatible(
            LLMRequest(messages=[{"role": "user", "content": "hi"}])
        )
    ]


@pytest.mark.asyncio
async def test_a_gateway_usage_on_the_last_content_chunk_without_a_total_is_accounted(
    monkeypatch,
):
    chunks = await _stream(
        monkeypatch,
        [
            _Response(
                200,
                [
                    "data:" + json.dumps({"choices": [{"delta": {"content": "hello"}}]}),
                    "data: "
                    + json.dumps(
                        {
                            "choices": [{"delta": {}, "finish_reason": "stop"}],
                            "usage": {
                                "prompt_tokens": 1000,
                                "completion_tokens": 100,
                                "prompt_tokens_details": {"cached_tokens": 800},
                            },
                        }
                    ),
                    "data: [DONE]",
                ],
            )
        ],
    )

    assert "".join(c.content for c in chunks) == "hello"
    final = [c for c in chunks if c.usage is not None][-1]
    assert final.usage.total_tokens == 1100
    assert final.usage.cached_prompt_tokens == 800
    assert final.cost == Decimal("0.48")


@pytest.mark.asyncio
async def test_a_rejected_call_raises_with_the_providers_status_and_words(monkeypatch):
    body = json.dumps({"error": {"message": "Insufficient credits", "code": 402}}).encode()

    with pytest.raises(LLMProviderHTTPError) as raised:
        await _stream(monkeypatch, [_Response(402, [], body), _Response(402, [], body)])

    assert raised.value.status_code == 402
    assert raised.value.provider_message == "Insufficient credits"


def test_the_cost_the_provider_reports_is_read_as_is():
    assert provider_reported_cost({"prompt_tokens": 10, "cost": 0.0042}) == Decimal("0.0042")
    assert provider_reported_cost(
        Usage(prompt_tokens=10, completion_tokens=1, total_tokens=11, cost=0.5)
    ) == Decimal("0.5")


@pytest.mark.parametrize("cost", [None, True, "n/a", -1, float("nan")])
def test_no_usable_reported_cost_is_none(cost):
    assert provider_reported_cost({"prompt_tokens": 10, "cost": cost}) is None


def test_a_reported_cost_wins_over_the_declared_prices():
    """Declared prices are approximate (a provider may charge more at peak hours)."""
    model = LLMModel(
        provider_type="openai",
        model_name="m",
        input_cost_per_token=Decimal("1.5e-7"),
        output_cost_per_token=Decimal("6e-7"),
    )
    response = model._parse_response(
        ModelResponse(
            id="x",
            choices=[
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "hi"},
                    "finish_reason": "stop",
                }
            ],
            usage={
                "prompt_tokens": 1000,
                "completion_tokens": 100,
                "total_tokens": 1100,
                "cost": 0.00042,
            },
        )
    )

    assert response.cost == Decimal("0.00042")
